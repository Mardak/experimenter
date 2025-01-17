import json
import os

from django.conf import settings
from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response

from experimenter.experiments.models import NimbusExperiment


class Significance:
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class BranchComparison:
    ABSOLUTE = "absolute"
    DIFFERENCE = "difference"
    UPLIFT = "relative_uplift"


class Metric:
    RETENTION = "retained"
    SEARCH = "search_count"
    DAYS_OF_USE = "days_of_use"
    USER_COUNT = "identity"


class Statistic:
    PERCENT = "percentage"
    BINOMIAL = "binomial"
    MEAN = "mean"
    COUNT = "count"


BRANCH_DATA = "branch_data"
PRIMARY_METRIC_SUFFIX = "_ever_used"
STATISTICS_FOLDER = "statistics"
METADATA_FOLDER = "metadata"


def load_data_from_gcs(path):
    return (
        json.loads(default_storage.open(path).read())
        if default_storage.exists(path)
        else None
    )


def get_results_metrics_map(primary_outcomes, secondary_outcomes):
    # A mapping of metric label to relevant statistic. This is
    # used to see which statistic will be used for each metric.
    RESULTS_METRICS_MAP = {
        Metric.RETENTION: set([Statistic.BINOMIAL]),
        Metric.SEARCH: set([Statistic.MEAN]),
        Metric.DAYS_OF_USE: set([Statistic.MEAN]),
        Metric.USER_COUNT: set([Statistic.COUNT, Statistic.PERCENT]),
    }
    primary_metrics_set = set()
    for outcome_slug in primary_outcomes:
        metric_id = f"{outcome_slug}{PRIMARY_METRIC_SUFFIX}"
        RESULTS_METRICS_MAP[metric_id] = set([Statistic.BINOMIAL])
        primary_metrics_set.add(metric_id)

    for outcome_slug in secondary_outcomes:
        RESULTS_METRICS_MAP[outcome_slug] = set([Statistic.MEAN])

    return RESULTS_METRICS_MAP, primary_metrics_set


def append_population_percentages(data):
    total_population = 0
    branches = {}
    for row in data:
        if row["metric"] == Metric.USER_COUNT:
            total_population += row["point"]
            branches[row["branch"]] = row["point"]

    for branch_name, branch_user_count in sorted(branches.items()):
        data.append(
            {
                "metric": Metric.USER_COUNT,
                "statistic": Statistic.PERCENT,
                "branch": branch_name,
                "point": round(branch_user_count / total_population * 100),
            }
        )


def compute_significance(lower, upper):
    if max(lower, upper, 0) == 0:
        return Significance.NEGATIVE
    if min(lower, upper, 0) == 0:
        return Significance.POSITIVE
    else:
        return Significance.NEUTRAL


def append_conversion_count(results, primary_metrics_set):
    for branch in results:
        branch_data = results[branch][BRANCH_DATA]
        for primary_metric in primary_metrics_set:
            absolute_user_counts = branch_data[Metric.USER_COUNT][
                BranchComparison.ABSOLUTE
            ]
            absolute_primary_metric_vals = branch_data[primary_metric][
                BranchComparison.ABSOLUTE
            ]

            population_count = absolute_user_counts["first"]["point"]
            conversion_percent = absolute_primary_metric_vals["first"]["point"]
            conversion_count = population_count * conversion_percent

            absolute_primary_metric_vals["first"]["count"] = conversion_count


def get_week_x_retention(week_index, weekly_data):
    weekly_data = weekly_data or []
    return [
        row
        for row in weekly_data
        if row["window_index"] == str(week_index) and row["metric"] == Metric.RETENTION
    ]


def append_retention_data(overall_data, weekly_data):
    # Try to get the two-week retention data. If it doesn't
    # exist (experiment was too short), settle for 1 week.
    retention_data = get_week_x_retention(2, weekly_data)
    if len(retention_data) == 0:
        retention_data = get_week_x_retention(1, weekly_data)

    overall_data.extend(retention_data)


def process_data_for_consumption(overall_data, weekly_data, experiment):
    append_population_percentages(overall_data)
    append_retention_data(overall_data, weekly_data)
    results, primary_metrics_set, other_metrics = generate_results_object(
        overall_data, experiment
    )
    append_conversion_count(results, primary_metrics_set)
    return results, other_metrics


def generate_results_object(data, experiment, window="overall"):
    # These are metrics sent from Jetstream that are not explicitly chosen
    # by users to be either primary or secondary
    other_metrics = {}
    results = {}

    result_metrics, primary_metrics_set = get_results_metrics_map(
        experiment.primary_outcomes, experiment.secondary_outcomes
    )
    for row in data:
        branch = row.get("branch")
        metric = row.get("metric")
        lower = row.get("lower")
        upper = row.get("upper")
        point = row.get("point")
        statistic = row.get("statistic")
        window_index = row.get("window_index")

        if (
            metric in result_metrics
            and statistic in result_metrics[metric]
            or statistic == Statistic.MEAN
        ):
            results[branch] = results.get(
                branch,
                {
                    "is_control": experiment.reference_branch.slug == branch,
                    BRANCH_DATA: {},
                },
            )

            results[branch][BRANCH_DATA][metric] = results[branch][BRANCH_DATA].get(
                metric,
                {
                    BranchComparison.ABSOLUTE: {"all": [], "first": {}},
                    BranchComparison.DIFFERENCE: {"all": [], "first": {}},
                    BranchComparison.UPLIFT: {"all": [], "first": {}},
                },
            )

            if metric == Metric.USER_COUNT and statistic == Statistic.PERCENT:
                results[branch][BRANCH_DATA][Metric.USER_COUNT]["percent"] = point
                continue

            comparison = row.get("comparison", BranchComparison.ABSOLUTE)
            if comparison == BranchComparison.DIFFERENCE and lower and upper:
                results[branch][BRANCH_DATA][metric].update(
                    {"significance": compute_significance(lower, upper)}
                )
            data_point = {
                "lower": lower,
                "upper": upper,
                "point": point,
            }
            if window == "weekly":
                data_point["window_index"] = window_index

            results_at_comparison = results[branch][BRANCH_DATA][metric][comparison]
            if len(results_at_comparison["all"]) == 0:
                results_at_comparison["first"] = data_point

            results[branch][BRANCH_DATA][metric][comparison]["all"].append(data_point)

            if metric not in result_metrics and window == "overall":
                metric_title = " ".join([word.title() for word in metric.split("_")])
                other_metrics[metric] = metric_title

    return results, primary_metrics_set, other_metrics


def get_data(slug, window):
    filename = f"statistics_{slug}_{window}.json"
    path = os.path.join(STATISTICS_FOLDER, filename)
    return load_data_from_gcs(path)


def get_metadata(slug):
    filename = f"metadata_{slug}.json"
    path = os.path.join(METADATA_FOLDER, filename)
    return load_data_from_gcs(path)


@api_view()
def analysis_results_view(request, slug):
    windows = ["daily", "weekly", "overall"]
    experiment = get_object_or_404(NimbusExperiment.objects.filter(slug=slug))
    raw_data = {}

    recipe_slug = experiment.slug.replace("-", "_")
    experiment_data = {
        "show_analysis": settings.FEATURE_ANALYSIS,
        "metadata": get_metadata(recipe_slug),
    }

    for window in windows:
        data = raw_data[window] = get_data(recipe_slug, window)

        if data and window == "overall":
            data, other_metrics = process_data_for_consumption(
                data, raw_data["weekly"], experiment
            )
            experiment_data["other_metrics"] = other_metrics
        elif data and window == "weekly":
            data, _, _ = generate_results_object(data, experiment, window)

        experiment_data[window] = data

    return Response(experiment_data)
