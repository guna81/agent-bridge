import Cocoa
import Foundation

// MARK: - Data Models

struct QueueStats: Decodable {
    let running: Int
    let waiting: Int
    let max_concurrency: Int
}

struct ProviderStat: Decodable {
    let name: String
    let kind: String
    let enabled: Bool
    let max_budget_usd: Double?
    let lifetime_cost_usd: Double
    let lifetime_requests: Int
    let lifetime_input_tokens: Int
    let lifetime_output_tokens: Int
    let today_cost_usd: Double
    let today_requests: Int
    let seven_days_cost_usd: Double
    let seven_days_requests: Int
}

struct TotalsStat: Decodable {
    let today_cost_usd: Double
    let today_requests: Int
    let seven_days_cost_usd: Double
    let seven_days_requests: Int
    let lifetime_cost_usd: Double
    let lifetime_requests: Int
}

struct LimitWindow: Decodable {
    let label: String?
    let used_percent: Int
    let left_percent: Int
    let reset_at: Int?
    let reset_str: String?
    let is_exhausted: Bool
}

struct ScopedLimitWindow: Decodable {
    let label: String?
    let model_name: String
    let used_percent: Int
    let left_percent: Int
    let reset_str: String?
    let is_exhausted: Bool
}

struct ProviderRateLimits: Decodable {
    let five_hour: LimitWindow?
    let weekly: LimitWindow?
    let weekly_scoped: ScopedLimitWindow?
    let claude_gpt_5h: LimitWindow?
    let claude_gpt_weekly: LimitWindow?
    let plan_name: String?
    let tier_id: String?
}

struct StatusBarServerConfig: Decodable {
    let pinned_metric: String?
    let refresh_interval_seconds: Int?
}

struct StatusBarResponse: Decodable {
    let online: Bool
    let port: Int
    let queue: QueueStats
    let providers: [ProviderStat]
    let totals: TotalsStat
    let credits_remaining_usd: Double
    let rate_limits: [String: ProviderRateLimits]?
    let config: StatusBarServerConfig?
}

// MARK: - Config & Environment

class AppConfig {
    static let shared = AppConfig()
    
    var host: String = "127.0.0.1"
    var port: Int = 8765
    var adminToken: String = ""
    var refreshInterval: TimeInterval = 3.0
    var projectRoot: String = ""
    
    init() {
        findProjectRoot()
        loadEnv()
        parseArgs()
    }
    
    private func findProjectRoot() {
        let fileManager = FileManager.default
        var dir = URL(fileURLWithPath: fileManager.currentDirectoryPath)
        for _ in 0..<5 {
            if fileManager.fileExists(atPath: dir.appendingPathComponent("backend/.env").path) {
                projectRoot = dir.path
                return
            }
            if fileManager.fileExists(atPath: dir.appendingPathComponent(".env").path) {
                projectRoot = dir.path
                return
            }
            let parent = dir.deletingLastPathComponent()
            if parent.path == dir.path { break }
            dir = parent
        }
        if projectRoot.isEmpty {
            projectRoot = "/Users/guna/Desktop/Development/ai-credit-proxy"
        }
    }
    
    private func loadEnv() {
        let envPaths = [
            URL(fileURLWithPath: projectRoot).appendingPathComponent("backend/.env").path,
            URL(fileURLWithPath: projectRoot).appendingPathComponent(".env").path,
            NSHomeDirectory() + "/.config/ai-credit-proxy/.env"
        ]
        
        for path in envPaths {
            guard let content = try? String(contentsOfFile: path, encoding: .utf8) else { continue }
            for line in content.components(separatedBy: .newlines) {
                let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
                if trimmed.isEmpty || trimmed.hasPrefix("#") { continue }
                let parts = trimmed.components(separatedBy: "=")
                guard parts.count >= 2 else { continue }
                let key = parts[0].trimmingCharacters(in: .whitespaces)
                let val = parts[1...].joined(separator: "=").trimmingCharacters(in: .whitespaces)
                    .trimmingCharacters(in: CharacterSet(charactersIn: "\"'"))
                
                if key == "PROXY_PORT", let p = Int(val) {
                    self.port = p
                } else if key == "PROXY_ADMIN_TOKEN" {
                    self.adminToken = val
                } else if key == "PROXY_HOST" {
                    self.host = val
                }
            }
            break
        }
    }
    
    private func parseArgs() {
        let args = CommandLine.arguments
        for i in 0..<args.count {
            if args[i] == "--port", i + 1 < args.count, let p = Int(args[i + 1]) {
                self.port = p
            } else if args[i] == "--token", i + 1 < args.count {
                self.adminToken = args[i + 1]
            } else if args[i] == "--host", i + 1 < args.count {
                self.host = args[i + 1]
            } else if args[i] == "--interval", i + 1 < args.count, let sec = Double(args[i + 1]) {
                self.refreshInterval = max(1.0, sec)
            }
        }
    }
    
    var endpointURL: URL {
        URL(string: "http://\(host):\(port)/admin/status-bar")!
    }
    
    var dashboardURL: URL {
        URL(string: "http://\(host):\(port)")!
    }
}

// MARK: - Status Bar Controller

class StatusBarController: NSObject {
    private var statusItem: NSStatusItem!
    private var timer: Timer?
    private var latestData: StatusBarResponse?
    private var isOffline: Bool = false
    private var lastSyncedServerPinnedMetric: String? = nil
    
    // Preferences: agent ("codex", "claude", "antigravity"), metric ("session", "weekly", etc.)
    private var selectedAgent: String {
        get { UserDefaults.standard.string(forKey: "selectedAgent") ?? "antigravity" }
        set { UserDefaults.standard.set(newValue, forKey: "selectedAgent") }
    }
    
    private var selectedMetric: String {
        get { UserDefaults.standard.string(forKey: "selectedMetric") ?? "session" }
        set { UserDefaults.standard.set(newValue, forKey: "selectedMetric") }
    }
    
    private var displayFormat: String {
        get { UserDefaults.standard.string(forKey: "displayFormat") ?? "standard" }
        set { UserDefaults.standard.set(newValue, forKey: "displayFormat") }
    }
    
    override init() {
        super.init()
        setupStatusItem()
        startPolling()
    }
    
    private func setupStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.imagePosition = .imageLeft
            button.title = " CLI..."
            button.toolTip = "CLI Usage & Limits"
        }
        rebuildMenu()
    }
    
    private func startPolling() {
        timer?.invalidate()
        fetchData()
        let interval = (latestData?.queue.running ?? 0) > 0 ? 1.0 : AppConfig.shared.refreshInterval
        timer = Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { [weak self] _ in
            self?.fetchData()
        }
    }
    
    // MARK: - Data Fetching
    
    private func fetchData() {
        var req = URLRequest(url: AppConfig.shared.endpointURL)
        req.timeoutInterval = 2.5
        let token = AppConfig.shared.adminToken
        if !token.isEmpty {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        
        let task = URLSession.shared.dataTask(with: req) { [weak self] data, _, error in
            guard let self = self else { return }
            
            if error != nil {
                DispatchQueue.main.async {
                    self.isOffline = true
                    self.updateUI()
                }
                return
            }
            
            guard let data = data else {
                DispatchQueue.main.async {
                    self.isOffline = true
                    self.updateUI()
                }
                return
            }
            
            do {
                let decoded = try JSONDecoder().decode(StatusBarResponse.self, from: data)
                DispatchQueue.main.async {
                    self.latestData = decoded
                    self.isOffline = false
                    if let pinned = decoded.config?.pinned_metric, pinned != self.lastSyncedServerPinnedMetric {
                        self.applyPinnedMetricKey(pinned)
                        self.lastSyncedServerPinnedMetric = pinned
                    }
                    self.updateUI()
                }
            } catch {
                DispatchQueue.main.async {
                    self.isOffline = true
                    self.updateUI()
                }
            }
        }
        task.resume()
    }
    
    // MARK: - UI Updates
    
    private func updateUI() {
        guard let button = statusItem.button else { return }
        
        if isOffline {
            button.image = drawOfflineIcon()
            button.title = " Offline"
            button.toolTip = "Gateway is unreachable on port \(AppConfig.shared.port)"
            rebuildMenu()
            return
        }
        
        guard let data = latestData else { return }
        let isRunning = data.queue.running > 0
        let prefix = isRunning ? "⚡ " : ""
        
        let agentLimits = data.rate_limits?[selectedAgent]
        
        // Compute progress fraction (0.0 to 1.0) and title string
        let progress: Double
        let titleText: String
        let isExhausted: Bool
        let isFillingUsed: Bool // Claude fills "used", Codex fills "left"
        
        if selectedAgent == "claude" {
            isFillingUsed = true
            if selectedMetric == "weekly" {
                let w = agentLimits?.weekly
                let used = w?.used_percent ?? 0
                progress = Double(used) / 100.0
                isExhausted = used >= 100
                let reset = w?.reset_str != nil ? " (\(w!.reset_str!))" : ""
                switch displayFormat {
                case "bar_only":
                    titleText = isRunning ? "⚡" : ""
                case "full":
                    titleText = "\(prefix)claude wk: \(used)% used\(reset)"
                default:
                    titleText = "\(prefix)claude wk: \(used)% used"
                }
            } else if selectedMetric == "weekly_scoped" {
                let sc = agentLimits?.weekly_scoped
                let used = sc?.used_percent ?? 0
                let mName = sc?.model_name.lowercased() ?? "fable"
                progress = Double(used) / 100.0
                isExhausted = used >= 100
                let reset = sc?.reset_str != nil ? " (\(sc!.reset_str!))" : ""
                switch displayFormat {
                case "bar_only":
                    titleText = isRunning ? "⚡" : ""
                case "full":
                    titleText = "\(prefix)\(mName): \(used)% used\(reset)"
                default:
                    titleText = "\(prefix)\(mName): \(used)% used"
                }
            } else {
                // Session (five_hour)
                let s = agentLimits?.five_hour
                let used = s?.used_percent ?? 0
                progress = Double(used) / 100.0
                isExhausted = used >= 100
                let reset = s?.reset_str != nil ? " (\(s!.reset_str!))" : ""
                switch displayFormat {
                case "bar_only":
                    titleText = isRunning ? "⚡" : ""
                case "full":
                    titleText = "\(prefix)claude: \(used)% used\(reset)"
                default:
                    titleText = "\(prefix)claude: \(used)% used"
                }
            }
        } else if selectedAgent == "antigravity" {
            // Antigravity: displays % left (just like Codex & Antigravity CLI)
            isFillingUsed = false
            if selectedMetric == "weekly" {
                let w = agentLimits?.weekly
                let left = w?.left_percent ?? 100
                progress = Double(left) / 100.0
                isExhausted = left == 0
                let reset = w?.reset_str != nil ? " (\(w!.reset_str!))" : ""
                switch displayFormat {
                case "bar_only":
                    titleText = isRunning ? "⚡" : ""
                case "full":
                    titleText = "\(prefix)agy wk: \(left)% left\(reset)"
                default:
                    titleText = "\(prefix)agy wk: \(left)% left"
                }
            } else if selectedMetric == "claude_gpt_5h" {
                let c = agentLimits?.claude_gpt_5h
                let left = c?.left_percent ?? 100
                progress = Double(left) / 100.0
                isExhausted = left == 0
                let reset = c?.reset_str != nil ? " (\(c!.reset_str!))" : ""
                switch displayFormat {
                case "bar_only":
                    titleText = isRunning ? "⚡" : ""
                case "full":
                    titleText = "\(prefix)agy 3p: \(left)% left\(reset)"
                default:
                    titleText = "\(prefix)agy 3p: \(left)% left"
                }
            } else if selectedMetric == "claude_gpt_weekly" {
                let c = agentLimits?.claude_gpt_weekly
                let left = c?.left_percent ?? 100
                progress = Double(left) / 100.0
                isExhausted = left == 0
                let reset = c?.reset_str != nil ? " (\(c!.reset_str!))" : ""
                switch displayFormat {
                case "bar_only":
                    titleText = isRunning ? "⚡" : ""
                case "full":
                    titleText = "\(prefix)agy 3pw: \(left)% left\(reset)"
                default:
                    titleText = "\(prefix)agy 3pw: \(left)% left"
                }
            } else {
                // 5-hour limit
                let f = agentLimits?.five_hour
                let left = f?.left_percent ?? 100
                progress = Double(left) / 100.0
                isExhausted = left == 0
                let reset = f?.reset_str != nil ? " (\(f!.reset_str!))" : ""
                switch displayFormat {
                case "bar_only":
                    titleText = isRunning ? "⚡" : ""
                case "full":
                    titleText = "\(prefix)agy 5h: \(left)% left\(reset)"
                default:
                    titleText = "\(prefix)agy 5h: \(left)% left"
                }
            }
        } else {
            // Codex: displays % left (just like Codex CLI)
            isFillingUsed = false
            if selectedMetric == "weekly" {
                let w = agentLimits?.weekly
                let left = w?.left_percent ?? 0
                progress = Double(left) / 100.0
                isExhausted = left == 0
                let reset = w?.reset_str != nil ? " (\(w!.reset_str!))" : ""
                switch displayFormat {
                case "bar_only":
                    titleText = isRunning ? "⚡" : ""
                case "full":
                    titleText = "\(prefix)codex wk: \(left)% left\(reset)"
                default:
                    titleText = "\(prefix)codex wk: \(left)% left"
                }
            } else {
                // 5-hour limit
                let f = agentLimits?.five_hour
                let left = f?.left_percent ?? 0
                progress = Double(left) / 100.0
                isExhausted = left == 0
                let reset = f?.reset_str != nil ? " (\(f!.reset_str!))" : ""
                switch displayFormat {
                case "bar_only":
                    titleText = isRunning ? "⚡" : ""
                case "full":
                    titleText = "\(prefix)codex 5h: \(left)% left\(reset)"
                default:
                    titleText = "\(prefix)codex 5h: \(left)% left"
                }
            }
        }
        
        button.image = drawProgressBar(fraction: progress, isFillingUsed: isFillingUsed, isExhausted: isExhausted, isRunning: isRunning)
        button.title = " \(titleText)"
        
        // Tooltip with complete status
        var tip = ""
        if let cl = data.rate_limits?["claude"] {
            tip += "CLAUDE CODE:\n"
            tip += "• Current session: \(cl.five_hour?.used_percent ?? 0)% used" + (cl.five_hour?.reset_str != nil ? " (resets \(cl.five_hour!.reset_str!))\n" : "\n")
            tip += "• Current week:    \(cl.weekly?.used_percent ?? 0)% used" + (cl.weekly?.reset_str != nil ? " (resets \(cl.weekly!.reset_str!))\n" : "\n")
            if let sc = cl.weekly_scoped {
                tip += "• Current week (\(sc.model_name)): \(sc.used_percent)% used\n"
            }
        }
        if let cx = data.rate_limits?["codex"] {
            tip += "\nCODEX CLI:\n"
            tip += "• 5h limit:     \(cx.five_hour?.left_percent ?? 0)% left" + (cx.five_hour?.reset_str != nil ? " (resets \(cx.five_hour!.reset_str!))\n" : "\n")
            tip += "• Weekly limit: \(cx.weekly?.left_percent ?? 0)% left" + (cx.weekly?.reset_str != nil ? " (resets \(cx.weekly!.reset_str!))\n" : "\n")
        }
        if let ag = data.rate_limits?["antigravity"] {
            tip += "\nGOOGLE ANTIGRAVITY:\n"
            if let plan = ag.plan_name {
                tip += "• Plan: \(plan)\n"
            }
            tip += "• Gemini 5h limit:     \(ag.five_hour?.left_percent ?? 0)% left" + (ag.five_hour?.reset_str != nil ? " (resets \(ag.five_hour!.reset_str!))\n" : "\n")
            tip += "• Gemini Weekly limit: \(ag.weekly?.left_percent ?? 0)% left" + (ag.weekly?.reset_str != nil ? " (resets \(ag.weekly!.reset_str!))\n" : "\n")
            if let c5 = ag.claude_gpt_5h {
                tip += "• Claude/GPT 5h:       \(c5.left_percent)% left" + (c5.reset_str != nil ? " (resets \(c5.reset_str!))\n" : "\n")
            }
            if let cw = ag.claude_gpt_weekly {
                tip += "• Claude/GPT Weekly:   \(cw.left_percent)% left" + (cw.reset_str != nil ? " (resets \(cw.reset_str!))\n" : "\n")
            }
        }
        button.toolTip = tip
        
        rebuildMenu()
    }
    
    // MARK: - Progress Bar Graphics
    
    private func drawProgressBar(fraction: Double, isFillingUsed: Bool, isExhausted: Bool, isRunning: Bool) -> NSImage {
        let width: CGFloat = 36
        let height: CGFloat = 10
        let radius: CGFloat = 5.0
        let size = NSSize(width: width, height: height)
        
        let image = NSImage(size: size, flipped: false) { rect in
            // Background track
            let trackPath = NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius)
            NSColor(white: 0.5, alpha: 0.22).setFill()
            trackPath.fill()
            
            // Border
            if isExhausted {
                NSColor(red: 0.95, green: 0.25, blue: 0.25, alpha: 0.85).setStroke()
                trackPath.lineWidth = 1.0
            } else {
                NSColor(white: 0.5, alpha: 0.20).setStroke()
                trackPath.lineWidth = 0.5
            }
            trackPath.stroke()
            
            // Filled portion
            let clamped = max(0.0, min(1.0, fraction))
            let fillWidth = rect.width * CGFloat(clamped)
            
            if fillWidth > 0 && !isExhausted {
                let fillRect = NSRect(x: 0, y: 0, width: max(radius * 1.5, fillWidth), height: height)
                let fillPath = NSBezierPath(roundedRect: fillRect, xRadius: radius, yRadius: radius)
                
                let fillColor: NSColor
                if isRunning {
                    fillColor = NSColor(red: 0.20, green: 0.60, blue: 1.00, alpha: 1.0)
                } else if isFillingUsed {
                    // Claude: fraction is % USED
                    if clamped < 0.70 {
                        // Light usage: Green
                        fillColor = NSColor(red: 0.20, green: 0.76, blue: 0.44, alpha: 1.0)
                    } else if clamped < 0.90 {
                        // Moderate: Amber
                        fillColor = NSColor(red: 1.00, green: 0.62, blue: 0.12, alpha: 1.0)
                    } else {
                        // High (>=90% used): Red
                        fillColor = NSColor(red: 0.95, green: 0.26, blue: 0.26, alpha: 1.0)
                    }
                } else {
                    // Codex: fraction is % LEFT
                    if clamped > 0.40 {
                        fillColor = NSColor(red: 0.20, green: 0.76, blue: 0.44, alpha: 1.0)
                    } else if clamped > 0.15 {
                        fillColor = NSColor(red: 1.00, green: 0.62, blue: 0.12, alpha: 1.0)
                    } else {
                        fillColor = NSColor(red: 0.95, green: 0.26, blue: 0.26, alpha: 1.0)
                    }
                }
                
                fillColor.setFill()
                fillPath.fill()
            }
            return true
        }
        image.isTemplate = false
        return image
    }
    
    private func drawOfflineIcon() -> NSImage {
        let size = NSSize(width: 14, height: 14)
        let image = NSImage(size: size, flipped: false) { rect in
            let path = NSBezierPath(ovalIn: rect.insetBy(dx: 1, dy: 1))
            NSColor.systemGray.withAlphaComponent(0.4).setFill()
            path.fill()
            
            let slash = NSBezierPath()
            slash.move(to: NSPoint(x: 3, y: 11))
            slash.line(to: NSPoint(x: 11, y: 3))
            NSColor.systemRed.setStroke()
            slash.lineWidth = 1.8
            slash.stroke()
            return true
        }
        image.isTemplate = false
        return image
    }
    
    private func unicodeBar(percent: Int, width: Int = 10) -> String {
        let clamped = max(0, min(100, percent))
        let filled = Int(round(Double(clamped) / 100.0 * Double(width)))
        let empty = width - filled
        return "[" + String(repeating: "█", count: filled) + String(repeating: " ", count: empty) + "]"
    }
    
    // MARK: - Menu Construction
    
    private func rebuildMenu() {
        let menu = NSMenu()
        menu.autoenablesItems = false
        
        let monospacedFont = NSFont.monospacedSystemFont(ofSize: 12, weight: .medium)
        
        // --- 1. Claude Code Section (Exact CLI UI) ---
        let claudeTitle = NSMenuItem(title: "CLAUDE CODE USAGE", action: nil, keyEquivalent: "")
        claudeTitle.isEnabled = false
        menu.addItem(claudeTitle)
        
        let clLimits = latestData?.rate_limits?["claude"]
        let clSession = clLimits?.five_hour
        let clWeekly = clLimits?.weekly
        let clScoped = clLimits?.weekly_scoped
        
        // Session
        let sUsed = clSession?.used_percent ?? 7
        let sBar = unicodeBar(percent: sUsed, width: 10)
        let sReset = clSession?.reset_str != nil ? " (Resets \(clSession!.reset_str!))" : ""
        let sTitle = String(format: "  Current session:            %@ %2d%% used%@", sBar, sUsed, sReset)
        let sItem = NSMenuItem(title: sTitle, action: #selector(quickSelectAction(_:)), keyEquivalent: "")
        sItem.target = self
        sItem.representedObject = ["agent": "claude", "metric": "session"]
        sItem.state = (selectedAgent == "claude" && selectedMetric == "session") ? .on : .off
        sItem.attributedTitle = NSAttributedString(string: sTitle, attributes: [.font: monospacedFont])
        menu.addItem(sItem)
        
        // Weekly (all models)
        let wUsed = clWeekly?.used_percent ?? 93
        let wBar = unicodeBar(percent: wUsed, width: 10)
        let wReset = clWeekly?.reset_str != nil ? " (Resets \(clWeekly!.reset_str!))" : ""
        let wTitle = String(format: "  Current week (all models):  %@ %2d%% used%@", wBar, wUsed, wReset)
        let wItem = NSMenuItem(title: wTitle, action: #selector(quickSelectAction(_:)), keyEquivalent: "")
        wItem.target = self
        wItem.representedObject = ["agent": "claude", "metric": "weekly"]
        wItem.state = (selectedAgent == "claude" && selectedMetric == "weekly") ? .on : .off
        wItem.attributedTitle = NSAttributedString(string: wTitle, attributes: [.font: monospacedFont])
        menu.addItem(wItem)
        
        // Weekly (Fable / Scoped)
        if let sc = clScoped {
            let scUsed = sc.used_percent
            let scBar = unicodeBar(percent: scUsed, width: 10)
            let scReset = sc.reset_str != nil ? " (Resets \(sc.reset_str!))" : ""
            let scTitle = String(format: "  Current week (%-12@): %@ %2d%% used%@", sc.model_name, scBar, scUsed, scReset)
            let scItem = NSMenuItem(title: scTitle, action: #selector(quickSelectAction(_:)), keyEquivalent: "")
            scItem.target = self
            scItem.representedObject = ["agent": "claude", "metric": "weekly_scoped"]
            scItem.state = (selectedAgent == "claude" && selectedMetric == "weekly_scoped") ? .on : .off
            scItem.attributedTitle = NSAttributedString(string: scTitle, attributes: [.font: monospacedFont])
            menu.addItem(scItem)
        }
        
        menu.addItem(NSMenuItem.separator())
        
        // --- 2. Codex CLI Section ---
        let codexTitle = NSMenuItem(title: "CODEX CLI LIMITS", action: nil, keyEquivalent: "")
        codexTitle.isEnabled = false
        menu.addItem(codexTitle)
        
        let cxLimits = latestData?.rate_limits?["codex"]
        let cx5h = cxLimits?.five_hour
        let cxWk = cxLimits?.weekly
        
        let cx5Left = cx5h?.left_percent ?? 0
        let cx5Bar = unicodeBar(percent: cx5Left, width: 10)
        let cx5Reset = cx5h?.reset_str != nil ? " (resets \(cx5h!.reset_str!))" : ""
        let cx5Title = String(format: "  5h limit:                   %@ %2d%% left%@", cx5Bar, cx5Left, cx5Reset)
        let cx5Item = NSMenuItem(title: cx5Title, action: #selector(quickSelectAction(_:)), keyEquivalent: "")
        cx5Item.target = self
        cx5Item.representedObject = ["agent": "codex", "metric": "session"]
        cx5Item.state = (selectedAgent == "codex" && selectedMetric == "session") ? .on : .off
        cx5Item.attributedTitle = NSAttributedString(string: cx5Title, attributes: [.font: monospacedFont])
        menu.addItem(cx5Item)
        
        let cxWkLeft = cxWk?.left_percent ?? 48
        let cxWkBar = unicodeBar(percent: cxWkLeft, width: 10)
        let cxWkReset = cxWk?.reset_str != nil ? " (resets \(cxWk!.reset_str!))" : ""
        let cxWkTitle = String(format: "  Weekly limit:               %@ %2d%% left%@", cxWkBar, cxWkLeft, cxWkReset)
        let cxWkItem = NSMenuItem(title: cxWkTitle, action: #selector(quickSelectAction(_:)), keyEquivalent: "")
        cxWkItem.target = self
        cxWkItem.representedObject = ["agent": "codex", "metric": "weekly"]
        cxWkItem.state = (selectedAgent == "codex" && selectedMetric == "weekly") ? .on : .off
        cxWkItem.attributedTitle = NSAttributedString(string: cxWkTitle, attributes: [.font: monospacedFont])
        menu.addItem(cxWkItem)
        
        menu.addItem(NSMenuItem.separator())
        
        // --- 3. Google Antigravity Section ---
        let agTitleText = (latestData?.rate_limits?["antigravity"]?.plan_name != nil) ?
            "GOOGLE ANTIGRAVITY (\(latestData!.rate_limits!["antigravity"]!.plan_name!))" : "GOOGLE ANTIGRAVITY"
        let agTitle = NSMenuItem(title: agTitleText, action: nil, keyEquivalent: "")
        agTitle.isEnabled = false
        menu.addItem(agTitle)
        
        let agLimits = latestData?.rate_limits?["antigravity"]
        let ag5h = agLimits?.five_hour
        let agWk = agLimits?.weekly
        let agC5 = agLimits?.claude_gpt_5h
        let agCW = agLimits?.claude_gpt_weekly
        
        let ag5Left = ag5h?.left_percent ?? 100
        let ag5Bar = unicodeBar(percent: ag5Left, width: 10)
        let ag5Reset = ag5h?.reset_str != nil ? " (resets \(ag5h!.reset_str!))" : ""
        let ag5Title = String(format: "  Gemini 5h limit:            %@ %2d%% left%@", ag5Bar, ag5Left, ag5Reset)
        let ag5Item = NSMenuItem(title: ag5Title, action: #selector(quickSelectAction(_:)), keyEquivalent: "")
        ag5Item.target = self
        ag5Item.representedObject = ["agent": "antigravity", "metric": "session"]
        ag5Item.state = (selectedAgent == "antigravity" && selectedMetric == "session") ? .on : .off
        ag5Item.attributedTitle = NSAttributedString(string: ag5Title, attributes: [.font: monospacedFont])
        menu.addItem(ag5Item)
        
        let agWkLeft = agWk?.left_percent ?? 100
        let agWkBar = unicodeBar(percent: agWkLeft, width: 10)
        let agWkReset = agWk?.reset_str != nil ? " (resets \(agWk!.reset_str!))" : ""
        let agWkTitle = String(format: "  Gemini weekly:              %@ %2d%% left%@", agWkBar, agWkLeft, agWkReset)
        let agWkItem = NSMenuItem(title: agWkTitle, action: #selector(quickSelectAction(_:)), keyEquivalent: "")
        agWkItem.target = self
        agWkItem.representedObject = ["agent": "antigravity", "metric": "weekly"]
        agWkItem.state = (selectedAgent == "antigravity" && selectedMetric == "weekly") ? .on : .off
        agWkItem.attributedTitle = NSAttributedString(string: agWkTitle, attributes: [.font: monospacedFont])
        menu.addItem(agWkItem)
        
        if let c5 = agC5 {
            let c5Left = c5.left_percent
            let c5Bar = unicodeBar(percent: c5Left, width: 10)
            let c5Reset = c5.reset_str != nil ? " (resets \(c5.reset_str!))" : ""
            let c5Title = String(format: "  Claude/GPT 5h:              %@ %2d%% left%@", c5Bar, c5Left, c5Reset)
            let c5Item = NSMenuItem(title: c5Title, action: #selector(quickSelectAction(_:)), keyEquivalent: "")
            c5Item.target = self
            c5Item.representedObject = ["agent": "antigravity", "metric": "claude_gpt_5h"]
            c5Item.state = (selectedAgent == "antigravity" && selectedMetric == "claude_gpt_5h") ? .on : .off
            c5Item.attributedTitle = NSAttributedString(string: c5Title, attributes: [.font: monospacedFont])
            menu.addItem(c5Item)
        }
        
        if let cw = agCW {
            let cwLeft = cw.left_percent
            let cwBar = unicodeBar(percent: cwLeft, width: 10)
            let cwReset = cw.reset_str != nil ? " (resets \(cw.reset_str!))" : ""
            let cwTitle = String(format: "  Claude/GPT weekly:          %@ %2d%% left%@", cwBar, cwLeft, cwReset)
            let cwItem = NSMenuItem(title: cwTitle, action: #selector(quickSelectAction(_:)), keyEquivalent: "")
            cwItem.target = self
            cwItem.representedObject = ["agent": "antigravity", "metric": "claude_gpt_weekly"]
            cwItem.state = (selectedAgent == "antigravity" && selectedMetric == "claude_gpt_weekly") ? .on : .off
            cwItem.attributedTitle = NSAttributedString(string: cwTitle, attributes: [.font: monospacedFont])
            menu.addItem(cwItem)
        }
        
        menu.addItem(NSMenuItem.separator())
        
        // --- 4. Status Bar Display Settings ---
        let viewMenu = NSMenu()
        var views = [
            ("Claude: Current session (\(sUsed)% used)", "claude", "session"),
            ("Claude: Current week (all models) (\(wUsed)% used)", "claude", "weekly"),
            ("Claude: Current week (\(clScoped?.model_name ?? "Fable")) (\(clScoped?.used_percent ?? 61)% used)", "claude", "weekly_scoped"),
            ("Codex: 5h limit (\(cx5Left)% left)", "codex", "session"),
            ("Codex: Weekly limit (\(cxWkLeft)% left)", "codex", "weekly"),
            ("Antigravity: Gemini 5h (\(ag5Left)% left)", "antigravity", "session"),
            ("Antigravity: Gemini Weekly (\(agWkLeft)% left)", "antigravity", "weekly")
        ]
        if let c5 = agC5 {
            views.append(("Antigravity: Claude/GPT 5h (\(c5.left_percent)% left)", "antigravity", "claude_gpt_5h"))
        }
        if let cw = agCW {
            views.append(("Antigravity: Claude/GPT Weekly (\(cw.left_percent)% left)", "antigravity", "claude_gpt_weekly"))
        }
        for (label, ag, met) in views {
            let item = NSMenuItem(title: label, action: #selector(selectAgentMetricAction(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = ["agent": ag, "metric": met]
            item.state = (selectedAgent == ag && selectedMetric == met) ? .on : .off
            viewMenu.addItem(item)
        }
        let viewSub = NSMenuItem(title: "Track In Status Bar", action: nil, keyEquivalent: "")
        viewSub.submenu = viewMenu
        menu.addItem(viewSub)
        
        let formatMenu = NSMenu()
        let formats = [
            ("standard", "Standard (e.g. claude: 7% used / codex 5h: 0% left)"),
            ("full", "Full Details with Reset Time"),
            ("bar_only", "Progress Bar Only")
        ]
        for (key, label) in formats {
            let item = NSMenuItem(title: label, action: #selector(changeFormatAction(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = key
            item.state = (displayFormat == key) ? .on : .off
            formatMenu.addItem(item)
        }
        let formatSub = NSMenuItem(title: "Status Bar Style", action: nil, keyEquivalent: "")
        formatSub.submenu = formatMenu
        menu.addItem(formatSub)
        
        menu.addItem(NSMenuItem.separator())
        
        // --- 4. Controls ---
        let dashItem = NSMenuItem(title: "🌐 Open Web Dashboard", action: #selector(openDashboardAction), keyEquivalent: "d")
        dashItem.target = self
        menu.addItem(dashItem)
        
        let refreshItem = NSMenuItem(title: "🔄 Refresh Now", action: #selector(refreshAction), keyEquivalent: "r")
        refreshItem.target = self
        menu.addItem(refreshItem)
        
        let svcMenu = NSMenu()
        let restartSvc = NSMenuItem(title: "Restart Gateway Service", action: #selector(restartServiceAction), keyEquivalent: "")
        restartSvc.target = self
        svcMenu.addItem(restartSvc)
        
        let stopSvc = NSMenuItem(title: "Stop Gateway Service", action: #selector(stopServiceAction), keyEquivalent: "")
        stopSvc.target = self
        svcMenu.addItem(stopSvc)
        
        let logsSvc = NSMenuItem(title: "Open Logs Directory", action: #selector(openLogsAction), keyEquivalent: "")
        logsSvc.target = self
        svcMenu.addItem(logsSvc)
        
        let svcSub = NSMenuItem(title: "⚙️ Service Controls", action: nil, keyEquivalent: "")
        svcSub.submenu = svcMenu
        menu.addItem(svcSub)
        
        menu.addItem(NSMenuItem.separator())
        
        let quitItem = NSMenuItem(title: "Quit Status Bar App", action: #selector(quitAction), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)
        
        statusItem.menu = menu
    }
    
    // MARK: - Actions
    
    private func applyPinnedMetricKey(_ key: String) {
        switch key {
        case "claude_session":
            selectedAgent = "claude"
            selectedMetric = "session"
        case "claude_weekly":
            selectedAgent = "claude"
            selectedMetric = "weekly"
        case "claude_weekly_scoped":
            selectedAgent = "claude"
            selectedMetric = "weekly_scoped"
        case "codex_session":
            selectedAgent = "codex"
            selectedMetric = "session"
        case "codex_weekly":
            selectedAgent = "codex"
            selectedMetric = "weekly"
        case "antigravity_gemini_5h":
            selectedAgent = "antigravity"
            selectedMetric = "session"
        case "antigravity_gemini_weekly":
            selectedAgent = "antigravity"
            selectedMetric = "weekly"
        case "antigravity_claude_5h":
            selectedAgent = "antigravity"
            selectedMetric = "claude_gpt_5h"
        case "antigravity_claude_weekly":
            selectedAgent = "antigravity"
            selectedMetric = "claude_gpt_weekly"
        default:
            break
        }
    }
    
    private func metricToKey(agent: String, metric: String) -> String {
        switch (agent, metric) {
        case ("claude", "session"): return "claude_session"
        case ("claude", "weekly"): return "claude_weekly"
        case ("claude", "weekly_scoped"): return "claude_weekly_scoped"
        case ("codex", "session"): return "codex_session"
        case ("codex", "weekly"): return "codex_weekly"
        case ("antigravity", "session"): return "antigravity_gemini_5h"
        case ("antigravity", "weekly"): return "antigravity_gemini_weekly"
        case ("antigravity", "claude_gpt_5h"): return "antigravity_claude_5h"
        case ("antigravity", "claude_gpt_weekly"): return "antigravity_claude_weekly"
        default: return "antigravity_gemini_5h"
        }
    }
    
    private func pushPinnedMetricToServer(agent: String, metric: String) {
        let key = metricToKey(agent: agent, metric: metric)
        lastSyncedServerPinnedMetric = key
        guard let url = URL(string: "http://\(AppConfig.shared.host):\(AppConfig.shared.port)/admin/status-bar/config") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !AppConfig.shared.adminToken.isEmpty {
            req.setValue("Bearer \(AppConfig.shared.adminToken)", forHTTPHeaderField: "Authorization")
        }
        let body: [String: Any] = ["pinned_metric": key]
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: req).resume()
    }
    
    @objc private func quickSelectAction(_ sender: NSMenuItem) {
        guard let dict = sender.representedObject as? [String: String],
              let ag = dict["agent"], let met = dict["metric"] else { return }
        selectedAgent = ag
        selectedMetric = met
        pushPinnedMetricToServer(agent: ag, metric: met)
        updateUI()
    }
    
    @objc private func selectAgentMetricAction(_ sender: NSMenuItem) {
        guard let dict = sender.representedObject as? [String: String],
              let ag = dict["agent"], let met = dict["metric"] else { return }
        selectedAgent = ag
        selectedMetric = met
        pushPinnedMetricToServer(agent: ag, metric: met)
        updateUI()
    }
    
    @objc private func changeFormatAction(_ sender: NSMenuItem) {
        guard let fmt = sender.representedObject as? String else { return }
        displayFormat = fmt
        updateUI()
    }
    
    @objc private func openDashboardAction() {
        NSWorkspace.shared.open(AppConfig.shared.dashboardURL)
    }
    
    @objc private func refreshAction() {
        fetchData()
    }
    
    @objc private func restartServiceAction() {
        runShellScript(args: ["restart"])
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) { [weak self] in
            self?.fetchData()
        }
    }
    
    @objc private func stopServiceAction() {
        runShellScript(args: ["stop"])
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
            self?.fetchData()
        }
    }
    
    @objc private func openLogsAction() {
        let logDir = URL(fileURLWithPath: NSHomeDirectory() + "/Library/Logs/ai-credit-proxy")
        NSWorkspace.shared.open(logDir)
    }
    
    @objc private func quitAction() {
        NSApplication.shared.terminate(nil)
    }
    
    private func runShellScript(args: [String]) {
        let scriptPath = URL(fileURLWithPath: AppConfig.shared.projectRoot).appendingPathComponent("manage-service.sh").path
        guard FileManager.default.fileExists(atPath: scriptPath) else { return }
        
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/bin/bash")
        proc.arguments = [scriptPath] + args
        try? proc.run()
    }
}

// MARK: - Application Delegate & Main

class AppDelegate: NSObject, NSApplicationDelegate {
    var statusBarController: StatusBarController?
    
    func applicationDidFinishLaunching(_ notification: Notification) {
        statusBarController = StatusBarController()
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
