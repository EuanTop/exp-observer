import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from backend.store import Store


EXAMPLE = Path(__file__).resolve().parents[1] / 'examples' / 'har-study'


def module(name):
    spec = importlib.util.spec_from_file_location(name, EXAMPLE / f'{name}.py')
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class HarExampleTests(unittest.TestCase):
    def test_relocated_example_imports_and_serves_original_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'English case with spaces'
            shutil.copytree(EXAMPLE, root)
            loader = module('load_example')
            project = loader.materialize(root)
            store = Store(Path(temporary) / 'platform')
            imported = store.import_project(loader.metadata_only(project))
            for artifact in project['artifacts']:
                store.register_artifact(imported['id'], artifact)
            imported = store.get_project(imported['id'])
            self.assertEqual(len(imported['nodes']), 20)
            self.assertEqual(len(imported['edges']), 36)
            self.assertEqual(sum(n['status'] == 'paused' for n in imported['nodes']), 1)
            self.assertEqual(len(imported['usageRecords']), 52)
            shutil.rmtree(root)  # The platform must retain its own verified evidence.
            for artifact in imported['artifacts']:
                raw, _ = store.artifact_content(imported['id'], artifact['id'])
                self.assertEqual(raw, Path(artifact['path']).read_bytes())

    def test_changed_or_missing_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'case'
            shutil.copytree(EXAMPLE, root)
            target = root / 'evidence/final-metrics.json'
            target.write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                module('load_example').materialize(root)
            target.unlink()
            with self.assertRaises(FileNotFoundError):
                module('load_example').materialize(root)

    def test_evidence_cannot_escape_the_example(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'case'
            shutil.copytree(EXAMPLE, root)
            path = root / 'project.en.json'
            project = json.loads(path.read_text())
            project['artifacts'][0]['path'] = '../outside.json'
            path.write_text(json.dumps(project), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'inside the example'):
                module('load_example').materialize(root)

    def test_retained_predictions_reproduce_published_test_scores(self):
        results = module('verify_predictions').verify()
        self.assertEqual(len(results), 4)
        self.assertTrue(all(result['test_rows'] == 2947 for result in results.values()))


if __name__ == '__main__':
    unittest.main()
