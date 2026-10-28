import importlib.util
import pathlib
import unittest

FILE = pathlib.Path(__file__).with_name('analyze_dag.py')

class CalculatorTests(unittest.TestCase):
    def analyze(self, tasks):
        self.assertTrue(FILE.exists(), 'DAG calculator has not been implemented')
        spec = importlib.util.spec_from_file_location('dag', FILE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.analyze({'unit': 'hours', 'tasks': tasks})

    def test_fork_join_float_and_multiple_finishes(self):
        r = self.analyze([
            {'id':'A','duration':2,'depends_on':[]},
            {'id':'B','duration':4,'depends_on':['A']},
            {'id':'C','duration':3,'depends_on':['A']},
            {'id':'D','duration':2,'depends_on':['B','C']},
            {'id':'E','duration':1,'depends_on':['C']},
            {'id':'F','duration':1,'depends_on':['D','E']},
            {'id':'G','duration':1,'depends_on':[]}])
        self.assertEqual(r['duration'],9)
        self.assertEqual(r['critical_paths'],[['A','B','D','F']])
        self.assertEqual(r['tasks']['C']['float'],1)
        self.assertEqual(r['tasks']['G']['float'],8)
        self.assertEqual(r['waves'],[['A','G'],['B','C'],['D','E'],['F']])

    def test_tied_paths_and_zero_duration_milestone(self):
        r = self.analyze([{'id':'A','duration':2}, {'id':'B','duration':2},
                          {'id':'M','duration':0,'depends_on':['A','B']}])
        self.assertEqual(r['critical_paths'],[['A','M'],['B','M']])

    def test_path_enumeration_is_bounded_but_edges_are_complete(self):
        tasks = [{'id': 'root', 'duration': 0}]
        previous = ['root']
        for level in range(8):
            current = [f'{level}a', f'{level}b']
            tasks.extend({'id': key, 'duration': 1, 'depends_on': previous} for key in current)
            previous = current
        tasks.append({'id': 'end', 'duration': 0, 'depends_on': previous})
        r = self.analyze(tasks)
        self.assertEqual(r['duration'], 8)
        self.assertEqual(len(r['critical_paths']), 100)
        self.assertTrue(r['critical_paths_truncated'])
        self.assertEqual(len(r['critical_edges']), 32)

    def test_invalid_graphs(self):
        for tasks in [[], [{'id':'A','duration':-1}], [{'id':'A','duration':True}],
                      [{'id':'A','duration':float('nan')}],
                      [{'id':'A','duration':1,'depends_on':['X']}],
                      [{'id':'A','duration':1},{'id':'A','duration':2}],
                      [{'id':'A','duration':1,'depends_on':['B']},
                       {'id':'B','duration':1,'depends_on':['A']}]]:
            with self.subTest(tasks=tasks), self.assertRaises(ValueError):
                self.analyze(tasks)

if __name__ == '__main__':
    unittest.main()
