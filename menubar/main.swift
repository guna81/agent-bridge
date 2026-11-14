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
    let used_percent: Double
    let left_percent: Double
    let reset_at: Int?
    let reset_str: String?
    let is_exhausted: Bool
}

struct ScopedLimitWindow: Decodable {
    let label: String?
    let model_name: String
    let used_percent: Double
    let left_percent: Double
    let reset_str: String?
    let is_exhausted: Bool
}

struct ProviderRateLimits: Decodable {
    let updated_at: UsageTimestamp?
    let is_stale: Bool?
    let refresh_error: String?
    let five_hour: LimitWindow?
    let weekly: LimitWindow?
    let weekly_scoped: ScopedLimitWindow?
    let claude_gpt_5h: LimitWindow?
    let claude_gpt_weekly: LimitWindow?
    let plan_name: String?
    let tier_id: String?
}

// Codex reports ISO timestamps, while Claude and Antigravity report epoch seconds.
enum UsageTimestamp: Decodable {
    case epoch(Double)
    case iso(String)

    init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer()
        if let seconds = try? value.decode(Double.self) { self = .epoch(seconds) }
        else { self = .iso(try value.decode(String.self)) }
    }

    var date: Date? {
        switch self {
        case .epoch(let seconds): return Date(timeIntervalSince1970: seconds)
        case .iso(let text): return ISO8601DateFormatter().date(from: text)
        }
    }
}

struct StatusBarServerConfig: Decodable {
    let indicator_enabled: Bool?
    let pinned_metric: String?
    let selected_clis: [String]?
    let refresh_interval_seconds: Int?
    let display_mode: String?
}

struct StatusBarResponse: Decodable {
    let online: Bool
    let port: Int
    let queue: QueueStats
    let providers: [ProviderStat]
    let totals: TotalsStat
    let credits_remaining_usd: Double
    let rate_limits: [String: ProviderRateLimits?]?
    let config: StatusBarServerConfig?
}

// MARK: - Config & Environment

class AppConfig {
    static let shared = AppConfig()
    
    var host: String = "127.0.0.1"
    var port: Int = 8765
    var adminToken: String = ""
    var refreshInterval: TimeInterval = 5.0
    var projectRoot: String = ""
    
    init() {
        findProjectRoot()
        loadEnv()
        if let host = ProcessInfo.processInfo.environment["PROXY_HOST"] { self.host = host }
        if let port = ProcessInfo.processInfo.environment["PROXY_PORT"], let value = Int(port) { self.port = value }
        if let token = ProcessInfo.processInfo.environment["PROXY_ADMIN_TOKEN"] { self.adminToken = token }
        parseArgs()
    }
    
    private func findProjectRoot() {
        let fileManager = FileManager.default
        let startingDirectories = [
            Bundle.main.bundleURL,
            URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL.deletingLastPathComponent(),
            URL(fileURLWithPath: fileManager.currentDirectoryPath)
        ]
        for start in startingDirectories {
            var dir = start
            for _ in 0..<8 {
                if fileManager.fileExists(atPath: dir.appendingPathComponent("backend/.env").path) ||
                    fileManager.fileExists(atPath: dir.appendingPathComponent(".env").path) {
                    projectRoot = dir.path
                    return
                }
                let parent = dir.deletingLastPathComponent()
                if parent.path == dir.path { break }
                dir = parent
            }
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
                if [2.0, 5.0, 10.0, 30.0].contains(sec) { self.refreshInterval = sec }
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
    private var pollingInterval: TimeInterval = 0
    private var isFetching = false
    
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
        schedulePolling(AppConfig.shared.refreshInterval)
    }

    private func schedulePolling(_ seconds: TimeInterval) {
        let interval = max(2, min(300, seconds))
        guard timer == nil || pollingInterval != interval else { return }
        timer?.invalidate()
        pollingInterval = interval
        let refreshTimer = Timer(timeInterval: interval, repeats: true) { [weak self] _ in
            self?.fetchData()
        }
        // Menu tracking uses a different run-loop mode from the default mode.
        RunLoop.main.add(refreshTimer, forMode: .common)
        timer = refreshTimer
    }
    
    // MARK: - Data Fetching
    
    private func fetchData() {
        // Config-save callbacks also call this method from URLSession workers.
        guard Thread.isMainThread else {
            DispatchQueue.main.async { [weak self] in self?.fetchData() }
            return
        }
        guard !isFetching else { return }
        isFetching = true
        var req = URLRequest(url: AppConfig.shared.endpointURL, cachePolicy: .reloadIgnoringLocalCacheData)
        req.timeoutInterval = 10
        let token = AppConfig.shared.adminToken
        if !token.isEmpty {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        
        let task = URLSession.shared.dataTask(with: req) { [weak self] data, response, error in
            guard let self = self else { return }
            DispatchQueue.main.async { self.isFetching = false }
            
            if error != nil || !(200..<300).contains((response as? HTTPURLResponse)?.statusCode ?? 0) {
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
                    self.schedulePolling(TimeInterval(decoded.config?.refresh_interval_seconds ?? 5))
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
        statusItem.isVisible = latestData?.config?.indicator_enabled ?? true
        guard let button = statusItem.button else { return }
        
        if isOffline {
            button.image = drawOfflineIcon()
            button.title = " Offline"
            button.toolTip = "Gateway is unreachable on port \(AppConfig.shared.port)"
            rebuildMenu()
            return
        }
        
        guard let data = latestData else { return }
        let selected = data.config?.selected_clis ?? [selectedAgent]
        let names = ["codex": "Codex", "claude": "Claude", "antigravity": "Antigravity"]
        button.image = data.config?.display_mode == "compact" ? drawBridgeIcon() : drawCompactUsage(selected: selected, data: data)
        button.title = ""
        button.toolTip = selected.map { name in
            let limits = data.rate_limits?[name] ?? nil
            func value(_ window: LimitWindow?) -> String {
                guard let window = window else { return "unavailable" }
                return String(format: "%.1f%% remaining", max(0, min(100, 100 - window.used_percent)))
            }
            return "\(names[name] ?? name): 5h \(value(limits?.five_hour)), weekly \(value(limits?.weekly))"
        }.joined(separator: "\n") + "\nBars and percentages show remaining capacity. Top: 5h, bottom: weekly"
        rebuildMenu()
    }

    private func drawBridgeIcon() -> NSImage {
        let image = NSImage(size: NSSize(width: 22, height: 20), flipped: false) { _ in
            NSColor.black.setStroke()
            let bridge = NSBezierPath()
            // The AgentBridge mark, adapted to a monochrome template for the menu bar.
            bridge.lineWidth = 1.7
            bridge.lineCapStyle = .round
            bridge.lineJoinStyle = .round
            bridge.move(to: NSPoint(x: 3, y: 6.75))
            bridge.line(to: NSPoint(x: 5.5, y: 6.75))
            bridge.line(to: NSPoint(x: 8.1, y: 11.5))
            bridge.curve(to: NSPoint(x: 9.9, y: 11.5), controlPoint1: NSPoint(x: 8.5, y: 12.25), controlPoint2: NSPoint(x: 9.5, y: 12.25))
            bridge.line(to: NSPoint(x: 12.5, y: 6.75))
            bridge.line(to: NSPoint(x: 15, y: 6.75))
            bridge.move(to: NSPoint(x: 7.3, y: 6.75))
            bridge.line(to: NSPoint(x: 10.7, y: 6.75))
            // Fill the taller, wider image while keeping the mark centered.
            let transform = AffineTransform(m11: 1.3, m12: 0, m21: 0, m22: 1.8, tX: -0.7, tY: -7.1)
            bridge.transform(using: transform)
            bridge.lineWidth *= 1.3
            bridge.stroke()
            return true
        }
        image.isTemplate = true
        return image
    }

    // Bars and labels show remaining capacity.
    private func drawCompactUsage(selected: [String], data: StatusBarResponse) -> NSImage {
        let apps = ["codex": "/Applications/ChatGPT.app", "claude": "/Applications/Claude.app", "antigravity": "/Applications/Gemini.app"]
        let icons = selected.map { provider -> NSImage? in
            guard let path = apps[provider], FileManager.default.fileExists(atPath: path) else { return nil }
            return NSWorkspace.shared.icon(forFile: path)
        }
        let image = NSImage(size: NSSize(width: CGFloat(selected.count * 72 - 4), height: 20), flipped: false) { _ in
            for (index, provider) in selected.enumerated() {
                let x = CGFloat(index * 72)
                if let icon = icons[index] {
                    icon.draw(in: NSRect(x: x, y: 2, width: 16, height: 16))
                } else {
                    let initial = ["codex": "O", "claude": "C", "antigravity": "G"][provider] ?? "?"
                    let attrs: [NSAttributedString.Key: Any] = [.font: NSFont.boldSystemFont(ofSize: 11), .foregroundColor: NSColor.labelColor]
                    (initial as NSString).draw(at: NSPoint(x: x + 2, y: 3), withAttributes: attrs)
                }
                let limits = data.rate_limits?[provider] ?? nil
                for (barIndex, window) in [limits?.five_hour, limits?.weekly].enumerated() {
                    let rect = NSRect(x: x + 18, y: barIndex == 0 ? 11 : 4, width: 20, height: 5)
                    NSColor.systemGray.withAlphaComponent(0.35).setFill()
                    NSBezierPath(roundedRect: rect, xRadius: 2, yRadius: 2).fill()
                    let label: String
                    if let window = window {
                        let used = max(0, min(1, window.used_percent / 100))
                        let remaining = 1 - used
                        let color: NSColor = used >= 0.9 ? .systemRed : used >= 0.7 ? .systemOrange : .systemGreen
                        if remaining > 0 {
                            color.setFill()
                            NSBezierPath(roundedRect: NSRect(x: rect.minX, y: rect.minY, width: max(1, rect.width * remaining), height: rect.height), xRadius: 2, yRadius: 2).fill()
                        }
                        label = String(format: "%.0f%%", remaining * 100)
                    } else { label = "—" }
                    let attrs: [NSAttributedString.Key: Any] = [.font: NSFont.monospacedDigitSystemFont(ofSize: 8, weight: .medium), .foregroundColor: NSColor.labelColor]
                    (label as NSString).draw(at: NSPoint(x: x + 41, y: barIndex == 0 ? 8 : 1), withAttributes: attrs)
                }
            }
            return true
        }
        image.isTemplate = false
        image.accessibilityDescription = "CLI remaining percentages and 5-hour and weekly capacity"
        return image
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
        let selected = latestData?.config?.selected_clis ?? [selectedAgent]
        let names = [("codex", "Codex"), ("claude", "Claude Code"), ("antigravity", "Antigravity")]
        for (id, name) in names {
            let header = NSMenuItem(title: name, action: nil, keyEquivalent: "")
            menu.addItem(header)
            let limits = latestData?.rate_limits?[id] ?? nil
            if id == "claude", let limits = limits {
                var freshness = limits.is_stale == true ? "Stale usage" : "Usage updated"
                if let date = limits.updated_at?.date {
                    freshness += " " + DateFormatter.localizedString(from: date, dateStyle: .short, timeStyle: .short)
                }
                menu.addItem(NSMenuItem(title: "  \(freshness)", action: nil, keyEquivalent: ""))
                if let error = limits.refresh_error {
                    menu.addItem(NSMenuItem(title: "  \(error)", action: nil, keyEquivalent: ""))
                }
            }
            for (label, window) in [("5-hour", limits?.five_hour), ("Weekly", limits?.weekly)] {
                let detail: String
                if let window = window {
                    detail = String(format: "%.1f%% remaining", max(0, min(100, 100 - window.used_percent))) + (window.reset_str.map { " · resets \($0)" } ?? "")
                } else { detail = "Unavailable" }
                let item = NSMenuItem(title: "  \(label): \(detail)", action: nil, keyEquivalent: "")
                menu.addItem(item)
            }
        }
        menu.addItem(.separator())
        let selection = NSMenu()
        selection.autoenablesItems = false
        for (id, name) in names {
            let item = NSMenuItem(title: name, action: #selector(toggleCLIAction(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = id
            item.state = selected.contains(id) ? .on : .off
            item.isEnabled = selected.contains(id) ? selected.count > 1 : selected.count < 2
            selection.addItem(item)
        }
        let selectItem = NSMenuItem(title: "CLIs in Menu Bar (up to 2)", action: nil, keyEquivalent: "")
        selectItem.submenu = selection
        menu.addItem(selectItem)
        let intervals = NSMenu()
        intervals.autoenablesItems = false
        let intervalOptions: [(Int, String)] = [
            (2, "2 seconds (Accurate, consumes battery)"),
            (5, "5 seconds (Balanced)"),
            (10, "10 seconds (Battery saver)"),
            (30, "30 seconds (Maximum battery saver)")
        ]
        for (seconds, title) in intervalOptions {
            let item = NSMenuItem(title: title, action: #selector(changeRefreshIntervalAction(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = seconds
            item.state = Int(pollingInterval) == seconds ? .on : .off
            item.isEnabled = !isOffline && latestData != nil
            intervals.addItem(item)
        }
        let intervalItem = NSMenuItem(title: "Refresh Interval", action: nil, keyEquivalent: "")
        intervalItem.submenu = intervals
        menu.addItem(intervalItem)
        menu.addItem(.separator())
        let dashboard = NSMenuItem(title: "Open Web Dashboard", action: #selector(openDashboardAction), keyEquivalent: "d")
        dashboard.target = self
        menu.addItem(dashboard)
        let refresh = NSMenuItem(title: "Refresh Now", action: #selector(refreshAction), keyEquivalent: "r")
        refresh.target = self
        menu.addItem(refresh)
        let quit = NSMenuItem(title: "Quit Status Bar App", action: #selector(quitAction), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)
        statusItem.menu = menu
    }

    @objc private func toggleCLIAction(_ sender: NSMenuItem) {
        guard let id = sender.representedObject as? String else { return }
        var selected = latestData?.config?.selected_clis ?? [selectedAgent]
        if selected.contains(id) { selected.removeAll { $0 == id } } else { selected.append(id) }
        guard (1...2).contains(selected.count), let url = URL(string: "http://\(AppConfig.shared.host):\(AppConfig.shared.port)/admin/status-bar/config") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !AppConfig.shared.adminToken.isEmpty { req.setValue("Bearer \(AppConfig.shared.adminToken)", forHTTPHeaderField: "Authorization") }
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["selected_clis": selected])
        URLSession.shared.dataTask(with: req) { [weak self] _, response, error in
            guard error == nil, let response = response as? HTTPURLResponse, (200..<300).contains(response.statusCode) else { return }
            self?.fetchData()
        }.resume()
    }

    @objc private func changeRefreshIntervalAction(_ sender: NSMenuItem) {
        guard let seconds = sender.representedObject as? Int,
              [2, 5, 10, 30].contains(seconds),
              let url = URL(string: "http://\(AppConfig.shared.host):\(AppConfig.shared.port)/admin/status-bar/config") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !AppConfig.shared.adminToken.isEmpty { req.setValue("Bearer \(AppConfig.shared.adminToken)", forHTTPHeaderField: "Authorization") }
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["refresh_interval_seconds": seconds])
        URLSession.shared.dataTask(with: req) { [weak self] _, response, error in
            guard error == nil, let response = response as? HTTPURLResponse, (200..<300).contains(response.statusCode) else { return }
            self?.fetchData()
        }.resume()
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
