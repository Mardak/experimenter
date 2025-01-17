from django.test import TestCase

from experimenter.experiments.changelog_utils import (
    NimbusExperimentChangeLogSerializer,
    generate_nimbus_changelog,
)
from experimenter.experiments.models import NimbusExperiment
from experimenter.experiments.tests.factories import NimbusExperimentFactory
from experimenter.experiments.tests.factories.nimbus import NimbusFeatureConfigFactory
from experimenter.openidc.tests.factories import UserFactory
from experimenter.outcomes import Outcomes
from experimenter.outcomes.tests import mock_valid_outcomes
from experimenter.projects.tests.factories import ProjectFactory


@mock_valid_outcomes
class TestNimbusExperimentChangeLogSerializer(TestCase):
    maxDiff = None

    def setUp(self):
        Outcomes.clear_cache()

    def test_outputs_expected_schema_for_empty_experiment(self):
        owner = UserFactory.create()
        experiment = NimbusExperiment.objects.create(owner=owner)
        data = dict(NimbusExperimentChangeLogSerializer(experiment).data)
        self.assertEqual(
            data,
            {
                "application": "",
                "branches": [],
                "channel": NimbusExperiment.Channel.NO_CHANNEL,
                "reference_branch": None,
                "feature_config": None,
                "firefox_min_version": NimbusExperiment.Version.NO_VERSION,
                "hypothesis": NimbusExperiment.HYPOTHESIS_DEFAULT,
                "risk_mitigation_link": "",
                "is_paused": False,
                "is_end_requested": False,
                "name": "",
                "owner": owner.email,
                "population_percent": "0.0000",
                "primary_outcomes": [],
                "secondary_outcomes": [],
                "projects": [],
                "proposed_duration": NimbusExperiment.DEFAULT_PROPOSED_DURATION,
                "proposed_enrollment": NimbusExperiment.DEFAULT_PROPOSED_ENROLLMENT,
                "public_description": "",
                "slug": "",
                "status": NimbusExperiment.Status.DRAFT.value,
                "targeting_config_slug": NimbusExperiment.TargetingConfig.NO_TARGETING,
                "total_enrolled_clients": 0,
            },
        )

    def test_outputs_expected_schema_for_complete_experiment(self):
        application = NimbusExperiment.Application.DESKTOP
        feature_config = NimbusFeatureConfigFactory.create()
        project = ProjectFactory.create()
        primary_outcome = Outcomes.by_application(application)[0].slug
        secondary_outcome = Outcomes.by_application(application)[1].slug

        experiment = NimbusExperimentFactory.create_with_status(
            NimbusExperiment.Status.COMPLETE,
            application=application,
            feature_config=feature_config,
            projects=[project],
            primary_outcomes=[primary_outcome],
            secondary_outcomes=[secondary_outcome],
        )
        data = dict(NimbusExperimentChangeLogSerializer(experiment).data)
        branches_data = [dict(b) for b in data.pop("branches")]
        control_branch_data = dict(data.pop("reference_branch"))
        self.assertEqual(
            data,
            {
                "application": experiment.application,
                "channel": experiment.channel,
                "feature_config": {
                    "name": feature_config.name,
                    "slug": feature_config.slug,
                    "description": feature_config.description,
                    "application": feature_config.application,
                    "owner_email": feature_config.owner_email,
                    "schema": feature_config.schema,
                },
                "firefox_min_version": experiment.firefox_min_version,
                "hypothesis": experiment.hypothesis,
                "risk_mitigation_link": experiment.risk_mitigation_link,
                "is_paused": experiment.is_paused,
                "is_end_requested": experiment.is_end_requested,
                "name": experiment.name,
                "owner": experiment.owner.email,
                "population_percent": str(experiment.population_percent),
                "primary_outcomes": [primary_outcome],
                "secondary_outcomes": [secondary_outcome],
                "projects": [project.slug],
                "proposed_duration": experiment.proposed_duration,
                "proposed_enrollment": experiment.proposed_enrollment,
                "public_description": experiment.public_description,
                "slug": experiment.slug,
                "status": experiment.status,
                "targeting_config_slug": experiment.targeting_config_slug,
                "total_enrolled_clients": experiment.total_enrolled_clients,
            },
        )
        self.assertEqual(
            control_branch_data,
            {
                "description": experiment.reference_branch.description,
                "feature_enabled": experiment.reference_branch.feature_enabled,
                "feature_value": experiment.reference_branch.feature_value,
                "name": experiment.reference_branch.name,
                "ratio": experiment.reference_branch.ratio,
                "slug": experiment.reference_branch.slug,
            },
        )
        for branch in experiment.branches.all():
            self.assertIn(
                {
                    "description": branch.description,
                    "feature_enabled": branch.feature_enabled,
                    "feature_value": branch.feature_value,
                    "name": branch.name,
                    "ratio": branch.ratio,
                    "slug": branch.slug,
                },
                branches_data,
            )


class TestGenerateNimbusChangeLog(TestCase):
    def setUp(self):
        self.user = UserFactory.create()

    def test_generate_nimbus_changelog_without_prior_change(self):
        experiment = NimbusExperimentFactory.create()

        self.assertEqual(experiment.changes.count(), 0)

        generate_nimbus_changelog(experiment, self.user)

        self.assertEqual(experiment.changes.count(), 1)

        change = experiment.changes.get()

        self.assertEqual(change.experiment, experiment)
        self.assertEqual(change.changed_by, self.user)
        self.assertEqual(change.old_status, None)
        self.assertEqual(change.new_status, NimbusExperiment.Status.DRAFT)
        self.assertEqual(
            change.experiment_data,
            dict(NimbusExperimentChangeLogSerializer(experiment).data),
        )

    def test_generate_nimbus_changelog_with_prior_change(self):
        experiment = NimbusExperimentFactory.create_with_status(
            NimbusExperiment.Status.DRAFT
        )

        self.assertEqual(experiment.changes.count(), 1)

        generate_nimbus_changelog(experiment, self.user)

        self.assertEqual(experiment.changes.count(), 2)

        change = experiment.latest_change()

        self.assertEqual(change.experiment, experiment)
        self.assertEqual(change.changed_by, self.user)
        self.assertEqual(change.old_status, NimbusExperiment.Status.DRAFT)
        self.assertEqual(change.new_status, NimbusExperiment.Status.DRAFT)
        self.assertEqual(
            change.experiment_data,
            dict(NimbusExperimentChangeLogSerializer(experiment).data),
        )
