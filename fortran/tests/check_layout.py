"""Run the native example and inspect every array with the Python reference."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'python'))
import numpy as np
from qvf import Reader
from qvf.validate import run

exe, output = sys.argv[1:]
subprocess.run([exe, output], check=True)
report = run(output)
assert report['ok'] and not report['findings'], report
with Reader(output) as reader:
    positions = np.array([[1.1, 1.2, 1.3], [2.1, 2.2, 2.3]])
    assert [a['position'] for a in reader.json('structure', 'structure')['atoms']] == positions.tolist()
    volumes = reader.sections_of('volume.generic')
    assert len(volumes) == 1
    expected = np.fromfunction(lambda i,j,k: 100*(i+1)+10*(j+1)+(k+1), (2,3,4))
    np.testing.assert_array_equal(reader.tensor(volumes[0].id, 'data').tolist(), expected)
    coords = np.stack([positions, positions+1])
    np.testing.assert_array_equal(reader.tensor('trajectory', 'coords').tolist(), coords)
    cell = np.array([[4,.1,.2],[.3,5,.4],[.5,.6,6]])
    np.testing.assert_array_equal(reader.tensor('trajectory', 'lattice').tolist(), np.stack([cell,2*cell]))
    np.testing.assert_array_equal(reader.tensor('trajectory', 'velocities').tolist(), coords/10)
    np.testing.assert_array_equal(reader.tensor('trajectory', 'gradient').tolist(), -coords/100)
    np.testing.assert_array_equal(reader.tensor('trajectory', 'times').tolist(), [0,.5])
    np.testing.assert_array_equal(reader.tensor('trajectory', 'energies').tolist(), [-1,-.9])
    np.testing.assert_array_equal(reader.tensor('wf', 'mo_coefficients').tolist(), [[.8,.6],[-.6,.8]])
    np.testing.assert_array_equal(reader.json('wf', 'mo_metadata')['energies'], [-.5,.1])
    np.testing.assert_array_equal(reader.json('wf', 'mo_metadata')['occupations'], [2,0])
print('Fortran archive: zero findings; all scalar, cell, trajectory and MO layouts match')
