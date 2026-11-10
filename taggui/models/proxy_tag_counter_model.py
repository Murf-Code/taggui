import re
from fnmatch import fnmatchcase

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel

from models.tag_counter_model import TagCounterModel
from utils.enums import AllTagsSortBy


def estimate_token_count(text: str) -> int:
    """TagBench's rough token estimate: words and symbols, long words
    count as several tokens."""
    bits = re.findall(r'[A-Za-z0-9]+|[^A-Za-z0-9\s]', text)
    return sum((len(bit) + 3) // 4 if len(bit) > 8 else 1 for bit in bits)


class ProxyTagCounterModel(QSortFilterProxyModel):
    def __init__(self, tag_counter_model: TagCounterModel, tokenizer=None):
        super().__init__()
        self.setSourceModel(tag_counter_model)
        self.tag_counter_model = tag_counter_model
        self.tokenizer = tokenizer
        self.token_counts: dict[str, int] = {}
        self.sort_by = None
        self.filter = None

    def get_token_count(self, tag: str) -> int:
        """CLIP tokens in a tag (cached), or a rough estimate without a
        tokenizer."""
        count = self.token_counts.get(tag)
        if count is None:
            if self.tokenizer is not None:
                # Subtract 2 for the start and end tokens.
                count = len(self.tokenizer(tag).input_ids) - 2
            else:
                count = estimate_token_count(tag)
            self.token_counts[tag] = count
        return count

    # Setting a sort role results in lots of calls to `data()` and is very
    # slow, so implement a custom `lessThan()` method instead.
    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        left_tag, left_count = self.tag_counter_model.most_common_tags[
            left.row()]
        right_tag, right_count = self.tag_counter_model.most_common_tags[
            right.row()]
        if self.sort_by == AllTagsSortBy.FREQUENCY:
            return left_count < right_count
        elif self.sort_by == AllTagsSortBy.NAME:
            return left_tag < right_tag
        elif self.sort_by == AllTagsSortBy.LENGTH:
            return len(left_tag) < len(right_tag)
        elif self.sort_by == AllTagsSortBy.TOKENS:
            left_tokens = self.get_token_count(left_tag)
            right_tokens = self.get_token_count(right_tag)
            if left_tokens != right_tokens:
                return left_tokens < right_tokens
            return left_tag < right_tag

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex):
        if self.filter is None:
            return True
        tag, _ = self.tag_counter_model.most_common_tags[source_row]
        return fnmatchcase(tag, f'*{self.filter}*')
