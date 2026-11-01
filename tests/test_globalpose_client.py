"""Queue/freshness behavior without loading the native model."""
from pathlib import Path
import sys,time,unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'frontend'))
from globalpose_client import GlobalPoseClient

class ClientTests(unittest.TestCase):
    def client(self):
        with patch('globalpose_client.threading.Thread'):
            return GlobalPoseClient()
    def test_result_expires_and_explicit_invalidation_drops_it(self):
        c=self.client();c.result=(10,np.tile(np.eye(3),(24,1,1)),np.zeros(3))
        self.assertIsNotNone(c.latest(10.1)[0]);self.assertIsNone(c.latest(10.31)[0])
        c.invalidate();self.assertIsNone(c.latest(10.1)[0]);c.close()
    def test_input_gap_resets_state_instead_of_integrating_unseen_time(self):
        c=self.client();a=np.zeros((6,3));r=np.tile(np.eye(3),(6,1,1))
        c.submit(a,a,r,10);g=c.generation
        c.submit(a,a,r,10.02);self.assertEqual(c.generation,g)
        c.submit(a,a,r,11);self.assertGreater(c.generation,g);c.close()
    def test_repeated_windows_ticks_and_older_samples_never_reach_worker(self):
        c=self.client();a=np.zeros((6,3));r=np.tile(np.eye(3),(6,1,1))
        for at in (10.,10.,9.99,float('nan'),10.016):c.submit(a,a,r,at)
        self.assertEqual(c.frames.qsize(),2)
        self.assertEqual([c.frames.get_nowait()[1] for _ in range(2)],[10.,10.016])
        self.assertEqual(c.dropped_frames,3);c.close()

    def test_overload_does_not_accumulate_unbounded_stale_frames(self):
        c=self.client();a=np.zeros((6,3));r=np.tile(np.eye(3),(6,1,1))
        for i in range(100):c.submit(a,a,r,10+i/60)
        self.assertLessEqual(c.frames.qsize(),8);self.assertGreater(c.dropped_frames,0);c.close()

if __name__=='__main__':unittest.main()
