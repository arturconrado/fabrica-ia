class AFlowOptimizerAdapter:
    def propose_candidate(self, workflow, feedback, score):
        return {
            "source_workflow_id": workflow,
            "candidate_workflow_id": f"{workflow}_candidate",
            "score": score,
            "modification_summary": "Candidate generated from production workflow evidence for later human review.",
        }

    def evaluate_candidate(self, candidate):
        return {"status": "candidate", "score": candidate.get("score", 0)}

    def record_experience(self, parent, child, score, modification):
        return {"parent": parent, "child": child, "score": score, "modification": modification}
