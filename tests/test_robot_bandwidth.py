"""Robot-local sampling, late-message barriers and metadata transport invariants."""
import copy
import unittest
from tools.robot_bandwidth import Source, Coordinator, Window, SOURCE_DEADLINE

class RobotBandwidthTests(unittest.TestCase):
    def setUp(self):
        self.now=10.;self.wire=[];self.results=[];self.readers={};self.destroyed=[]
        self.catalog=[{'name':f'/camera_{i}','type':'sensor_msgs/msg/Image'} for i in range(10)]
        def subscribe(t,n,cb):self.readers[n]=cb;return n
        def destroy(n):self.destroyed.append(n);self.readers.pop(n,None)
        self.source=Source(lambda v:self.wire.append(('reply',copy.deepcopy(v))),lambda:self.catalog,subscribe,destroy,lambda:self.now)
        self.coordinator=Coordinator(lambda v:self.wire.append(('request',copy.deepcopy(v))),self.results.append,lambda:self.now)
        self.source.presence();self.pump()

    def pump(self):
        while self.wire:
            direction,v=self.wire.pop(0)
            (self.source.handle if direction=='request' else self.coordinator.receive)(v)

    def test_ten_topics_sample_concurrently_and_all_readers_close_before_result(self):
        self.coordinator.command({'op':'sample','id':'one'});self.pump()
        self.assertEqual(len(self.readers),10)
        for i in range(11):
            self.now=10+i*.1
            for callback in list(self.readers.values()):callback(bytes(100))
        self.source.step();self.pump()
        self.assertEqual(self.readers,{})
        result=self.results[-1];self.assertTrue(result['closed']);self.assertEqual(len(result['topics']),10)
        for row in result['topics'].values():self.assertAlmostEqual(row['bytes_per_second'],1000)
        self.assertLessEqual(self.now-10,1.01)
        self.now+=5;self.source.step();self.coordinator.step();self.pump()
        self.assertEqual(len([v for v in self.results if 'topics' in v]),1)

    def test_stop_invalidates_delayed_sample_and_ack_follows_destroy(self):
        self.coordinator.command({'op':'sample','id':'one'});late=copy.deepcopy(self.wire[0][1]);self.pump()
        self.assertTrue(self.readers)
        self.coordinator.command({'op':'stop','id':'stop'});self.pump()
        self.assertEqual(len(self.destroyed),10);self.assertTrue(self.results[-1]['closed'])
        # Old request, even from another session with a fresh sequence, carries
        # the old epoch and cannot recreate sensor readers after the barrier.
        late['client']='a'*32;late['seq']=100
        self.source.handle(late);self.pump();self.assertFalse(self.readers)
        self.source.handle(late);self.pump();self.assertFalse(self.readers)

    def test_missing_robot_ack_is_not_a_successful_stop(self):
        self.coordinator.command({'op':'sample','id':'one'});self.pump()
        self.coordinator.command({'op':'stop','id':'stop'});self.wire.clear()
        self.now+=2.6;self.coordinator.step()
        self.assertFalse(self.results[-1]['closed'])
        self.assertIn('confirm stopping',self.results[-1]['error'])

    def test_silent_and_low_frequency_topics_are_unknown_not_zero_and_deadline_is_bounded(self):
        self.coordinator.command({'op':'sample','id':'one'});self.pump()
        self.readers['/camera_0'](bytes(10))
        self.now+=SOURCE_DEADLINE+.01;self.source.step();self.pump()
        self.assertFalse(self.readers)
        for row in self.results[-1]['topics'].values():self.assertIsNone(row['bytes_per_second'])

    def test_old_command_expired_epoch_and_duplicate_request_cannot_resample(self):
        self.coordinator.command({'op':'sample','id':'one'});request=self.wire.pop()[1]
        self.now+=3.1;self.source.handle(request);self.pump();self.assertFalse(self.readers)
        self.coordinator.command({'op':'sample','id':'expired','expires':self.now-.1});self.assertFalse(self.readers)
        self.assertFalse(self.results[-1]['closed'])  # Earlier issued work still requires a stop ACK.

    def test_no_robot_or_multiple_sources_do_not_start_sampling(self):
        self.coordinator.peers={};self.coordinator.command({'op':'sample','id':'none'})
        self.assertIn('unavailable',self.results[-1]['error']);self.assertFalse(self.readers)
        self.source.presence();self.pump();self.coordinator.receive({'op':'presence','source':'b'*32,'epoch':'c'*32})
        self.coordinator.command({'op':'sample','id':'many'})
        self.assertIn('Multiple',self.results[-1]['error']);self.assertFalse(self.readers)

    def test_window_does_not_retain_payload_and_requires_observed_intervals(self):
        w=Window();w.add(100,0);self.assertIsNone(w.rate());w.add(100,.05);self.assertIsNone(w.rate())
        w.add(100,.1);self.assertAlmostEqual(w.rate(),2000)
        self.assertFalse(any(isinstance(v,bytes) for v in vars(w).values()))

if __name__=='__main__':unittest.main()
