"""measure.kan42_core must time the real object's stage once, and keep it the real object."""

import unittest

from measure.kan42_core import _instrumented
from measure.stages import RunRecorder


class Policy:
    """Shaped like DevicePolicy: a public method that calls another public method."""

    def tick(self):
        return "tick"

    def observe(self):
        return self.tick() + "+observe"


class InstrumentationTests(unittest.TestCase):
    def test_the_built_object_is_still_the_real_class(self):
        built = []
        factory = _instrumented(Policy, RunRecorder(), "policy", ("observe",), built)
        instance = factory()
        self.assertIsInstance(instance, Policy)
        self.assertEqual(built, [instance])

    def test_a_nested_call_to_the_same_stage_is_timed_once(self):
        recorder = RunRecorder()
        policy = _instrumented(Policy, recorder, "policy", ("observe", "tick"), [])()
        self.assertEqual(policy.observe(), "tick+observe")
        self.assertEqual(recorder.summary()["stages"]["policy"]["passes"], 1)
        policy.tick()
        self.assertEqual(recorder.summary()["stages"]["policy"]["passes"], 2)

    def test_a_stage_that_raises_is_recorded_and_the_error_kept(self):
        class Broken:
            def predict(self):
                raise ValueError("model refused")

        recorder = RunRecorder()
        detector = _instrumented(Broken, recorder, "inference", ("predict",), [])()
        with self.assertRaises(ValueError):
            detector.predict()
        self.assertEqual(recorder.summary()["failed_stages"], ["inference"])


if __name__ == "__main__":
    unittest.main()
