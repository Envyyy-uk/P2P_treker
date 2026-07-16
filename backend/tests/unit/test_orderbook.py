"""OrderBook: snapshot/delta, sequence gap detection, sorted views (Фаза 4, п.1)."""

from decimal import Decimal

from app.orderbook.book import OrderBook

D = Decimal


def test_apply_snapshot_sets_state():
    book = OrderBook()
    book.apply_snapshot(bids=[(D("100"), D("1"))], asks=[(D("101"), D("2"))], sequence=10)
    assert book.synced
    assert book.sequence == 10
    assert book.best_bid().price == D("100")
    assert book.best_ask().price == D("101")


def test_snapshot_filters_zero_quantity_levels():
    book = OrderBook()
    book.apply_snapshot(bids=[(D("100"), D("0"))], asks=[(D("101"), D("1"))], sequence=1)
    assert book.best_bid() is None


def test_delta_before_snapshot_rejected():
    book = OrderBook()
    ok = book.apply_delta(bids=[(D("100"), D("1"))], asks=[], sequence=1)
    assert not ok
    assert not book.synced


def test_delta_updates_existing_level():
    book = OrderBook()
    book.apply_snapshot(bids=[(D("100"), D("1"))], asks=[(D("101"), D("1"))], sequence=1)
    ok = book.apply_delta(bids=[(D("100"), D("5"))], asks=[], sequence=2)
    assert ok
    assert book.best_bid().quantity == D("5")


def test_delta_zero_quantity_removes_level():
    book = OrderBook()
    book.apply_snapshot(bids=[(D("100"), D("1")), (D("99"), D("1"))], asks=[], sequence=1)
    book.apply_delta(bids=[(D("100"), D("0"))], asks=[], sequence=2)
    assert book.best_bid().price == D("99")


def test_delta_adds_new_level():
    book = OrderBook()
    book.apply_snapshot(bids=[(D("100"), D("1"))], asks=[], sequence=1)
    book.apply_delta(bids=[(D("102"), D("3"))], asks=[], sequence=2)
    assert book.best_bid().price == D("102")


def test_sequence_gap_marks_desynced():
    book = OrderBook()
    book.apply_snapshot(bids=[(D("100"), D("1"))], asks=[], sequence=1)
    ok = book.apply_delta(bids=[(D("99"), D("1"))], asks=[], sequence=5)  # gap: expected 2
    assert not ok
    assert not book.synced


def test_stale_or_duplicate_sequence_ignored_without_desync():
    book = OrderBook()
    book.apply_snapshot(bids=[(D("100"), D("1"))], asks=[], sequence=5)
    ok = book.apply_delta(bids=[(D("999"), D("1"))], asks=[], sequence=5)  # duplicate
    assert ok
    assert book.synced
    assert book.best_bid().price == D("100")  # not applied


def test_resync_after_desync_via_new_snapshot():
    book = OrderBook()
    book.apply_snapshot(bids=[(D("100"), D("1"))], asks=[], sequence=1)
    book.apply_delta(bids=[], asks=[], sequence=10)  # gap -> desync
    assert not book.synced
    book.apply_snapshot(bids=[(D("200"), D("1"))], asks=[(D("201"), D("1"))], sequence=20)
    assert book.synced
    assert book.best_bid().price == D("200")


def test_bids_sorted_descending():
    book = OrderBook()
    book.apply_snapshot(
        bids=[(D("100"), D("1")), (D("102"), D("1")), (D("101"), D("1"))], asks=[], sequence=1
    )
    prices = [level.price for level in book.bids_sorted()]
    assert prices == [D("102"), D("101"), D("100")]


def test_asks_sorted_ascending():
    book = OrderBook()
    book.apply_snapshot(
        bids=[], asks=[(D("103"), D("1")), (D("101"), D("1")), (D("102"), D("1"))], sequence=1
    )
    prices = [level.price for level in book.asks_sorted()]
    assert prices == [D("101"), D("102"), D("103")]


def test_empty_book_best_levels_none():
    book = OrderBook()
    assert book.best_bid() is None
    assert book.best_ask() is None


def test_depth_counts_levels():
    book = OrderBook()
    book.apply_snapshot(
        bids=[(D("100"), D("1")), (D("99"), D("1"))], asks=[(D("101"), D("1"))], sequence=1
    )
    assert book.depth() == (2, 1)
