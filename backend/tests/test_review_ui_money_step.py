from pathlib import Path
import unittest


class ReviewUiMoneyStepTest(unittest.TestCase):
    def test_money_number_inputs_use_cent_step(self):
        html = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "ui"
            / "review.html"
        ).read_text(encoding="utf-8")

        self.assertIn(
            """const step=type==="number"?' step="0.01"':"";""",
            html,
        )
        self.assertIn('type="${type}"${step}', html)

        for marker in (
            'field("f_price","Cena €",val(e,"price_eur"),"number")',
            'field("f_regular","Parastā cena €",val(e,"regular_price_eur"),"number")',
            'field("f_app","Lidl Plus cena €",val(e,"app_price_eur"),"number")',
        ):
            self.assertIn(marker, html)


if __name__ == "__main__":
    unittest.main()
