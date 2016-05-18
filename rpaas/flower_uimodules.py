import tornado.web


class FixTasks(tornado.web.UIModule):
    def embedded_css(self):
        return """
#tasks-table, .dataTable {
    table-layout: fixed;
}
#tasks-table th:nth-child(3), .dataTable th:nth-child(3) {
    width: 50px !important;
}
#tasks-table th:nth-child(4), .dataTable th:nth-child(4) {
    width: 180px !important;
}
#tasks-table th:nth-child(5), .dataTable th:nth-child(5) {
    width: 50px !important;
}
#tasks-table td:nth-child(4) {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
"""

    def render(*args, **kwargs):
        pass
