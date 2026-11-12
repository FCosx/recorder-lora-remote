import tempfile
import unittest
from pathlib import Path

from hardware_status import CpuTemperature


class CpuTemperatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reader = CpuTemperature(self.root)

    def put(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        return path

    def test_amd_cpu_is_used_instead_of_acpi_or_gpu_temperature(self):
        self.put('class/thermal/thermal_zone0/type', 'acpitz')
        self.put('class/thermal/thermal_zone0/temp', '30000')
        self.put('class/hwmon/hwmon0/name', 'amdgpu')
        self.put('class/hwmon/hwmon0/temp1_input', '42000')
        self.put('class/hwmon/hwmon2/name', 'k10temp')
        self.put('class/hwmon/hwmon2/temp1_label', 'Tctl')
        self.put('class/hwmon/hwmon2/temp1_input', '51234')
        self.assertEqual(self.reader.read(), 51.2)

    def test_pi_cpu_thermal_zone_remains_supported_and_updates(self):
        self.put('class/thermal/thermal_zone0/type', 'cpu-thermal')
        path = self.put('class/thermal/thermal_zone0/temp', '48123')
        self.assertEqual(self.reader.read(), 48.1)
        path.write_text('55700')
        self.assertEqual(self.reader.read(), 55.7)

    def test_intel_package_sensor_is_preferred_to_individual_core(self):
        self.put('class/hwmon/hwmon1/name', 'coretemp')
        self.put('class/hwmon/hwmon1/temp1_label', 'Core 0')
        self.put('class/hwmon/hwmon1/temp1_input', '45000')
        self.put('class/hwmon/hwmon1/temp2_label', 'Package id 0')
        self.put('class/hwmon/hwmon1/temp2_input', '54000')
        self.assertEqual(self.reader.read(), 54.0)

    def test_unknown_acpi_is_not_labeled_as_cpu_and_bad_values_are_unknown(self):
        self.put('class/thermal/thermal_zone0/type', 'acpitz')
        self.put('class/thermal/thermal_zone0/temp', '30000')
        self.assertIsNone(self.reader.read())
        path = self.put('explicit', 'NaN')
        self.assertIsNone(self.reader.read(path))
        path.write_text('invalid')
        self.assertIsNone(self.reader.read(path))
        path.unlink()
        self.assertIsNone(self.reader.read(path))
