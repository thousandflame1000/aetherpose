"""Real-thread checks for dynamics clock, stale acknowledgements and resets."""
from pathlib import Path
import sys,time,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'frontend'))
from globalpose_rates import DynamicsClock,StaleObservation

class Net:
    def __init__(self):self.dt=1/60;self.resets=0;self.steps=[]
    def rnn_initialize(self):self.resets+=1
    def _advance_dynamics(self,*prediction):
        self.steps.append(self.dt)
        return prediction[0],prediction[1]

class RateTests(unittest.TestCase):
    def test_physics_continues_between_neural_observations_without_refreshing_timestamp(self):
        net=Net();clock=DynamicsClock(net)
        try:
            at=time.monotonic();clock.observe(('rotation','translation'),at)
            result=clock.wait(at,1)
            self.assertEqual(result[:3],('rotation','translation',at))
            count=len(net.steps);time.sleep(.06)
            self.assertGreater(len(net.steps),count)
            self.assertEqual(clock.result[2],at)
            self.assertLessEqual(max(net.steps),1/60+1e-6)
        finally:clock.close()
    def test_expired_neural_sample_returns_a_stale_ack_instead_of_hanging(self):
        clock=DynamicsClock(Net())
        try:
            at=time.monotonic()-1;clock.observe(('r','t'),at)
            with self.assertRaises(StaleObservation):clock.wait(at,.5)
        finally:clock.close()
    def test_reset_clears_previous_result_and_uses_new_epoch(self):
        net=Net();clock=DynamicsClock(net)
        try:
            at=time.monotonic();clock.observe(('old','old'),at);clock.wait(at,1)
            clock.reset();self.assertIsNone(clock.result);self.assertEqual(net.resets,1)
            at=time.monotonic();clock.observe(('new','new'),at)
            result=clock.wait(at,1);self.assertEqual(result[0],'new');self.assertEqual(result[3],1)
        finally:clock.close()

if __name__=='__main__':unittest.main()
