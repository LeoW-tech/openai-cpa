import unittest

from scripts import analyze_registration_success as analysis


class RegistrationSuccessAnalysisTests(unittest.TestCase):
    def test_convert_utc_naive_string_to_shanghai(self):
        converted = analysis.convert_utc_naive_to_timezone(
            "2026-04-19 16:30:00",
            "Asia/Shanghai",
        )

        self.assertEqual("2026-04-20 00:30:00", converted)

    def test_unknown_policy_exclude_removes_unknown_from_denominator(self):
        rate = analysis.compute_closed_success_rate(
            total_count=10,
            success_count=3,
            unknown_count=4,
            unknown_policy="exclude",
        )

        self.assertAlmostEqual(0.5, rate)

    def test_unknown_policy_include_counts_unknown_in_denominator(self):
        rate = analysis.compute_closed_success_rate(
            total_count=10,
            success_count=3,
            unknown_count=4,
            unknown_policy="include",
        )

        self.assertAlmostEqual(0.3, rate)

    def test_wait_bucket_boundaries(self):
        self.assertEqual("no_wait", analysis.classify_wait_bucket(None))
        self.assertEqual("<30s", analysis.classify_wait_bucket(29))
        self.assertEqual("30-44s", analysis.classify_wait_bucket(30))
        self.assertEqual("45-59s", analysis.classify_wait_bucket(45))
        self.assertEqual("60-74s", analysis.classify_wait_bucket(60))
        self.assertEqual("75-89s", analysis.classify_wait_bucket(75))
        self.assertEqual(">=90s", analysis.classify_wait_bucket(90))

    def test_min_sample_filter_marks_segments_below_threshold(self):
        segments = [
            {"segment": "A", "total_count": 35, "success_count": 20, "unknown_count": 2},
            {"segment": "B", "total_count": 29, "success_count": 18, "unknown_count": 1},
        ]

        ranked = analysis.rank_segments(
            segments,
            min_sample=30,
            unknown_policy="exclude",
            segment_key="segment",
        )

        self.assertEqual(1, len(ranked["qualified"]))
        self.assertEqual("A", ranked["qualified"][0]["segment"])
        self.assertEqual("B", ranked["unqualified"][0]["segment"])
        self.assertFalse(ranked["unqualified"][0]["eligible_for_ranking"])

    def test_transition_period_detects_records_without_token_wait(self):
        run_config = {"login_delay_min": 30, "login_delay_max": 90}

        self.assertTrue(
            analysis.is_transition_period_attempt(
                started_at_utc="2026-04-18 12:00:00",
                token_wait_duration_ms=None,
                run_config=run_config,
            )
        )
        self.assertFalse(
            analysis.is_transition_period_attempt(
                started_at_utc="2026-04-19 12:00:00",
                token_wait_duration_ms=45000,
                run_config=run_config,
            )
        )

    def test_build_funnel_rows_calculates_step_and_total_conversion(self):
        counts = {
            "total": 100,
            "email_acquired": 80,
            "phone_gate_hit": 60,
            "account_registered_pending_token": 50,
            "token_wait_scheduled": 40,
            "success": 10,
        }

        rows = analysis.build_funnel_rows(counts)
        by_stage = {row["stage"]: row for row in rows}

        self.assertEqual(1.0, by_stage["total"]["step_conversion_rate"])
        self.assertEqual(0.8, by_stage["token_wait_scheduled"]["step_conversion_rate"])
        self.assertEqual(0.25, by_stage["success"]["step_conversion_rate"])
        self.assertEqual(0.1, by_stage["success"]["total_conversion_rate"])


if __name__ == "__main__":
    unittest.main()
