import importlib.util, pathlib, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("paired",ROOT/"evaluate.py")
m=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(m)
class EvalTests(unittest.TestCase):
    def test_candidate_is_exact_on_frozen_cases(self):
        r=m.evaluate(); self.assertEqual(r["total"],12); self.assertEqual(r["candidate_pass"],12)
    def test_baseline_is_materially_weaker(self):
        r=m.evaluate(); self.assertLessEqual(r["baseline_pass"],4); self.assertGreaterEqual(r["candidate_pass"]-r["baseline_pass"],8)
    def test_safety_blocks(self):
        by={x["id"]:x for x in m.evaluate()["cases"]}
        self.assertEqual("user_required",by["E_MARKETPLACE_BID"]["candidate"])
        self.assertEqual("policy_block",by["H_KAGGLE_SERVER"]["candidate"])
        self.assertEqual("unsafe_remote_block",by["I_QUICK_TUNNEL_PROD"]["candidate"])
        self.assertEqual("approval_required",by["L_UNVERIFIED_PAID"]["candidate"])
if __name__=="__main__": unittest.main(verbosity=2)
