import unittest

from note_charts import parse_ultrastar


class ChartChecks(unittest.TestCase):
    def test_tempo_gap_duet_and_freestyle(self):
        data = parse_ultrastar('#VERSION:1.0.0\n#BPM:120\n#GAP:1000\n#TITLE:Song\n#P2:Guest\n'
                               'P1\n: 8 4 0 la\nF 12 4 10 spoken\nP2\n* 16 8 -12 hey\nE', 10)
        self.assertEqual(data['voices']['1'], [{'start': 2, 'end': 2.5, 'note': 60}])
        self.assertEqual(data['voices']['2'], [{'start': 3, 'end': 4, 'note': 48}])
        self.assertEqual(data['voice_names']['2'], 'Guest')

    def test_relative_and_bad_input(self):
        data = parse_ultrastar('#BPM:60\n#RELATIVE:yes\n: 0 4 0 a\n- 4 8\n: 0 4 2 b\nE', 10)
        self.assertEqual([b['start'] for b in data['voices']['1']], [0, 2])
        with self.assertRaises(ValueError):
            parse_ultrastar('#BPM:0\n: 0 4 0 a', 10)
        with self.assertRaises(ValueError):
            parse_ultrastar('#BPM:120\n: 9999 4 0 a', 10)

    def test_offset_is_applied_before_clipping_and_overlaps_are_rejected(self):
        data = parse_ultrastar('#BPM:60\n#GAP:-500\n: 0 4 0 a\n: 40 4 2 b\nE', 10)
        self.assertEqual(data['voices']['1'][0]['start'], -.5)
        self.assertEqual(data['voices']['1'][1]['end'], 10.5)
        with self.assertRaisesRegex(ValueError, 'перекрываются'):
            parse_ultrastar('#BPM:60\n: 0 4 0 a\n: 2 4 2 b\nE', 10)


if __name__ == '__main__':
    unittest.main()
