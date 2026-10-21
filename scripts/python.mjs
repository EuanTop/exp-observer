// Select a supported Python installation without depending on Unix command aliases.
import { spawnSync } from 'node:child_process';

const candidates = process.platform === 'win32'
  ? [['python'], ['py', '-3'], ['python3']]
  : [['python3'], ['python']];
const check = 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)';
const python = candidates.find(([command, ...prefix]) => {
  const probe = spawnSync(command, [...prefix, '-c', check], { stdio: 'ignore' });
  return !probe.error && probe.status === 0;
});

if (!python) {
  console.error('ExpObserver requires Python 3.10+. Install Python and add it to PATH.');
  process.exitCode = 1;
} else {
  const [command, ...prefix] = python;
  const result = spawnSync(command, [...prefix, ...process.argv.slice(2)], { stdio: 'inherit' });
  if (result.error) console.error(result.error.message);
  process.exitCode = result.status ?? (result.signal === 'SIGINT' ? 130 : 1);
}