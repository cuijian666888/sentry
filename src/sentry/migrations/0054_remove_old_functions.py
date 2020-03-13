# -*- coding: utf-8 -*-
# Generated by Django 1.11.28 on 2020-03-11 15:29
from __future__ import unicode_literals

import six
import re

from django.db import migrations
from django.db.models import Q

from sentry.utils.query import RangeQuerySetWrapperWithProgressBar


FIELDS_TO_CHANGE = set(["orderby", "fields", "yAxis", "query"])
FUNCTION_CHANGE = {
    "p75": "p75()",
    "p95": "p95()",
    "p99": "p99()",
    "apdex": "apdex(300)",
    "impact": "impact(300)",
    "last_seen": "last_seen()",
    "latest_event": "latest_event()",
}
COUNT_REGEX = re.compile(".*(count\([a-zA-Z\._]+\)).*")


def get_function_alias(field):
    match = FUNCTION_PATTERN.search(field)
    columns = [c.strip() for c in match.group("columns").split(",") if len(c.strip()) > 0]
    return get_function_alias_with_columns(match.group("function"), columns)


def convert_function(field, count_default="count()", transform=None):
    if transform is None:
        transform = lambda x: x

    if "count" in field and "count_unique" not in field:
        field = count_default
        return field

    for old_fn, new_fn in six.iteritems(FUNCTION_CHANGE):
        if old_fn + "()" in field:
            field = field.replace(old_fn + "()", transform(new_fn))
        elif old_fn in field:
            field = field.replace(old_fn, transform(new_fn))

    return field


def convert(DiscoverSavedQuery, saved_query):
    old_query = saved_query.query
    new_query = {}

    for key in old_query:
        if key in FIELDS_TO_CHANGE:
            continue

        new_query[key] = old_query[key]

    orderby = old_query.get("orderby")
    if orderby:
        new_query["orderby"] = convert_function(
            orderby, count_default="count", transform=get_function_alias
        )

    yAxis = old_query.get("yAxis")
    if yAxis:
        new_query["yAxis"] = convert_function(yAxis)

    fields = old_query.get("fields")
    new_fields = []
    for field in fields:
        new_fields.append(convert_function(field))
    new_query["fields"] = new_fields

    search = old_query.get("query")
    if search:
        match = COUNT_REGEX.match(search)
        if match:
            search = search.replace(match.groups()[0], "count()")
        for old_fn, new_fn in six.iteritems(FUNCTION_CHANGE):
            if old_fn + "()" in search:
                search = search.replace(old_fn + "()", new_fn)
            elif old_fn in search:
                search = search.replace(old_fn, new_fn)
        new_query["query"] = search

    DiscoverSavedQuery.objects.filter(id=saved_query.id).update(query=new_query)


def migrate_functions_in_queries(apps, schema_editor):
    """
    Creates v2 versions of existing v1 queries
    """
    DiscoverSavedQuery = apps.get_model("sentry", "DiscoverSavedQuery")

    """
    Seq Scan on sentry_discoversavedquery (cost=0.00..225.15 rows=1077 width=200) (actual time=0.054..7.875 rows=1037 loops=1)
    Filter: ((version = 2) AND ((query ~~ '%p95%'::text) OR (query ~~ '%p99%'::text) OR (query ~~ '%p75%'::text) OR (query ~~ '%apdex%'::text) OR (query ~~ '%impact%'::text) OR (query ~~ '%last_seen%'::text) OR (query ~~ '%latest_event%'::text) OR (query ~~ '%count(%'::text)))
    Rows Removed by Filter: 2074
    Planning time: 2.305 ms
    Execution time: 8.694 ms
    """
    function_filter = Q(query__contains="count(")
    for key in FUNCTION_CHANGE:
        function_filter |= Q(query__contains=key)

    queryset = DiscoverSavedQuery.objects.filter(function_filter, version=2)

    for query in RangeQuerySetWrapperWithProgressBar(queryset):
        convert(DiscoverSavedQuery, query)


class Migration(migrations.Migration):
    is_dangerous = False
    atomic = False

    dependencies = [
        ("sentry", "0053_migrate_alert_task_onboarding"),
    ]

    operations = [
        migrations.RunPython(migrate_functions_in_queries, reverse_code=migrations.RunPython.noop),
    ]
