"""Build an unpacked, relocatable AgentBridge distribution for this host."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
out = root / 'build' / 'release'
if not (root / 'frontend' / 'dist' / 'index.html').exists():
    raise SystemExit('Build the frontend first: cd frontend && npm ci && npm run build')
if out.exists():
    shutil.rmtree(out)
out.mkdir(parents=True)
env = os.environ.copy()
env['PYTHONPATH'] = str(root / 'backend')
command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
           '--name', 'agentbridge', '--distpath', str(out), '--workpath', str(root / 'build' / 'pyinstaller'),
           '--specpath', str(root / 'build'), '--paths', str(root / 'backend'),
           '--collect-submodules', 'app', '--collect-submodules', 'uvicorn',
           '--hidden-import', 'sqlalchemy.dialects.sqlite',
           '--hidden-import', 'sqlalchemy.dialects.sqlite.pysqlite']
if sys.platform != 'darwin':
    command += ['--collect-submodules', 'pystray']
    if sys.platform.startswith('linux'):
        env['PYSTRAY_BACKEND'] = 'dummy'  # The build runner may not have a display.
        command += ['--hidden-import', 'pystray._xorg']
    elif os.name == 'nt':
        command += ['--hidden-import', 'pystray._win32']
command.append(str(root / 'scripts' / 'frozen_entry.py'))
subprocess.run(command, check=True, env=env)
package = out / 'agentbridge'
shutil.copytree(root / 'frontend' / 'dist', package / 'frontend' / 'dist')
if sys.platform == 'darwin':
    native = root / 'menubar' / 'LLMGatewayBar'
    if not native.exists():
        raise SystemExit('Build the menu bar first: ./menubar/build.sh')
    (package / 'menubar').mkdir()
    shutil.copy2(native, package / 'menubar' / native.name)
print(f'Package ready: {package}')
