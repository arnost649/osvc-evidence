"""Shared, fixed-size server pagination for overview tables."""
from dataclasses import dataclass
from urllib.parse import urlencode
from flask import request, url_for
from .db import query

PAGE_SIZE = 100

@dataclass
class Pagination:
    total: int
    page: int
    per_page: int = PAGE_SIZE
    page_parameter: str = 'page'
    fragment: str = ''

    @property
    def pages(self):
        return max(1, (self.total + self.per_page - 1) // self.per_page)

    @property
    def numbers(self):
        visible = {1, self.pages}
        visible.update(range(max(1, self.page - 1), min(self.pages, self.page + 1) + 1))
        if self.page <= 2:
            visible.update(range(1, min(3, self.pages) + 1))
        if self.page >= self.pages - 1:
            visible.update(range(max(1, self.pages - 2), self.pages + 1))
        result = []
        for number in sorted(visible):
            if result and number - result[-1] > 1:
                result.append(None)
            result.append(number)
        return result

    def url(self, page):
        args = request.args.copy()
        args.setlist(self.page_parameter, [str(page)])
        return url_for(request.endpoint, **(request.view_args or {})) + '?' + urlencode(list(args.items(multi=True))) + ('#' + self.fragment if self.fragment else '')


def paginate(sql, params=(), count_sql=None, page_parameter='page', fragment=''):
    """SQL supplied by application code must include deterministic ordering."""
    total = query(count_sql or ('SELECT COUNT(*) AS total FROM (' + sql + ') pagination_count'), params, one=True)['total']
    requested = request.args.get(page_parameter, 1, type=int) or 1
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    pager = Pagination(total, min(max(1, requested), pages), page_parameter=page_parameter, fragment=fragment)
    rows = query(sql + ' LIMIT %s OFFSET %s', tuple(params) + (PAGE_SIZE, (pager.page - 1) * PAGE_SIZE))
    return rows, pager
