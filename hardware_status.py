"""CPU temperature from Linux hwmon or CPU thermal zones, with no background work."""
import math
from pathlib import Path


class CpuTemperature:
    def __init__(self, sys_root=Path('/sys')):
        self.root = Path(sys_root)
        self.path = None

    def _find(self):
        candidates = []
        try:
            monitors = sorted((self.root / 'class/hwmon').glob('hwmon*'))
        except OSError:
            monitors = []
        drivers = {'k10temp': 0, 'coretemp': 1, 'cpu_thermal': 2}
        for monitor in monitors:
            try:
                driver = (monitor / 'name').read_text().strip()
                if driver not in drivers:
                    continue
                for source in sorted(monitor.glob('temp*_input')):
                    label_path = source.with_name(source.name.replace('_input', '_label'))
                    try:
                        label = label_path.read_text().strip().lower()
                    except OSError:
                        label = ''
                    rank = 0 if label == 'tdie' or label.startswith('package id') else 1 if label == 'tctl' else 2
                    candidates.append((drivers[driver], rank, str(source), source))
            except OSError:
                continue
        if candidates:
            return min(candidates)[-1]
        for zone in sorted((self.root / 'class/thermal').glob('thermal_zone*')):
            try:
                kind = (zone / 'type').read_text().strip().lower()
                if 'cpu' in kind or kind == 'x86_pkg_temp':
                    return zone / 'temp'
            except OSError:
                continue
        return None

    def read(self, path=None):
        explicit = path is not None
        if not explicit and self.path is None:
            self.path = self._find()
        source = Path(path) if explicit else self.path
        if source is None:
            return None
        try:
            value = float(source.read_text().strip()) / 1000
            return round(value, 1) if math.isfinite(value) else None
        except (OSError, ValueError):
            if not explicit:
                self.path = None
            return None


_cpu_temperature = CpuTemperature()


def cpu_temperature(path=None):
    return _cpu_temperature.read(path)
