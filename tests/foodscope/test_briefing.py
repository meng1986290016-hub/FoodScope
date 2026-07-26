from src.foodscope.briefing import partition_brief_items
from tests.foodscope.test_selector import scored_item


def test_partition_brief_items_uses_six_point_boundary_and_no_duplicates():
    must_read = scored_item("six", importance=6.0)
    must_read.metadata.update(
        {
            "foodscope_base_score": 6.0,
            "foodscope_final_score": 7.2,
        }
    )
    news = scored_item("below-six", importance=5.99)
    news.metadata.update(
        {
            "foodscope_base_score": 5.99,
            "foodscope_final_score": 7.188,
        }
    )

    important, ordinary = partition_brief_items(
        [news, must_read],
        [must_read],
    )

    assert important == [must_read]
    assert ordinary == [news]
