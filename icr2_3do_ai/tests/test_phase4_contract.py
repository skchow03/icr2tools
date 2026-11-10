"""Phase 4 contract smoke tests: checked-in skill, instructions and CI artifacts."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".agents" / "skills" / "icr2-3do-modeler" / "SKILL.md"
WORKFLOW = ROOT / ".github" / "workflows" / "3do-ai-inspector.yml"
README = ROOT / "icr2_3do_ai" / "README.md"
AGENTS = ROOT / "icr2_3do_ai" / "AGENTS.md"
RELEASE = ROOT / "icr2_3do_ai" / "PHASE4_RELEASE.md"


class RepositoryContractTests(unittest.TestCase):
    def test_modeler_skill_names_actual_supported_command_and_separates_job_branch(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: icr2-3do-modeler\n"))
        for keyword in ("generate", "preview", "compare",
                        "release_package", "assembly", "surface_checks",
                        "HELMET", "SHA256SUMS", "feature/3do-ai-stage3-modeling-jobs-20261108"):
            self.assertIn(keyword,text)
        self.assertIn("Do not invoke or recommend build-job",text)
        self.assertIn("never merge",text.casefold())

    def test_documentation_names_review_only_release(self):
        for path in (README,AGENTS,RELEASE):
            text=path.read_text(encoding="utf-8")
            self.assertIn("release",text.lower(),path.name)
            self.assertTrue("PMP" in text and "candidate" in text.lower())
        self.assertIn("3do-ai-release-candidate", README.read_text())
        self.assertIn("3do-ai-generated-models", RELEASE.read_text())

    def test_workflow_no_automatic_publish_and_has_two_artifacts(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:",text)
        self.assertIn("3do-ai-generated-models",text)
        self.assertIn("3do-ai-release-candidate",text)
        self.assertIn("icr2_3do_ai.release_package",text)
        self.assertIn("sha256sum",text)
        self.assertIn(".agents/skills/icr2-3do-modeler/**",text)
        self.assertNotIn("softprops/action-gh-release",text)
        self.assertNotIn("gh release create",text)


if __name__ == "__main__":
    unittest.main()
