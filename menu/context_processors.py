from .table_context import resolve_remembered_table_context, table_context_template_values


def remembered_table_context(request):
    resolved = resolve_remembered_table_context(request)

    if not resolved:
        return {}

    ordering_context, table = resolved
    return table_context_template_values(ordering_context, table)
