// ==============================================================================
// PM2 Ecosystem Configuration for LLM CLI Gateway (ai-credit-proxy)
// Works on macOS, Linux, and Windows with Node.js & PM2
// Usage:
//   npm install -g pm2
//   pm2 start ecosystem.config.cjs
//   pm2 save
//   pm2 startup
// ==============================================================================

const path = require('path');
const os = require('os');

const isWin = process.platform === 'win32';
const backendDir = path.resolve(__dirname, 'backend');
const pythonBin = isWin
  ? path.resolve(backendDir, '.venv', 'Scripts', 'python.exe')
  : path.resolve(backendDir, '.venv', 'bin', 'python');

module.exports = {
  apps: [
    {
      name: 'ai-credit-proxy',
      script: 'run.py',
      cwd: backendDir,
      interpreter: pythonBin,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 2000,
      env: {
        PYTHONUNBUFFERED: '1',
      },
      out_file: path.resolve(backendDir, 'server.log'),
      error_file: path.resolve(backendDir, 'server.err.log'),
      merge_logs: true,
    },
  ],
};
