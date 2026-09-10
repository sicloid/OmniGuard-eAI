from core.schema import Classification, DetectionResult, FeatureVector, probability


class FakeDetector:
    """Fixed score sequence, explicitly fails when exhausted; never enforces policy."""

    def __init__(self, scores=(0.1, 0.1, 0.9, 0.9, 0.9), threshold: float = 0.5):
        self.scores = tuple(scores)
        probability(threshold, "threshold")
        for score in self.scores:
            probability(score, "score")
        self.threshold = threshold
        self.index = 0

    def predict(self, vector: FeatureVector) -> DetectionResult:
        if self.index >= len(self.scores):
            raise StopIteration("fake detector sequence exhausted")
        score = self.scores[self.index]
        self.index += 1
        classification = (
            Classification.ANOMALOUS if score >= self.threshold else Classification.NORMAL
        )
        return DetectionResult(
            vector.device_id,
            vector.window_start,
            "STUB-NOT-TRAINED",
            "0.1",
            score,
            classification,
            self.threshold,
        )
