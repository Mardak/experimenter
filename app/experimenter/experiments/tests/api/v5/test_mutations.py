import json

from django.conf import settings
from django.urls import reverse
from graphene_django.utils.testing import GraphQLTestCase

from experimenter.experiments.constants.nimbus import NimbusConstants
from experimenter.experiments.models.nimbus import NimbusExperiment, NimbusFeatureConfig
from experimenter.experiments.tests.factories.nimbus import (
    NimbusExperimentFactory,
    NimbusFeatureConfigFactory,
)
from experimenter.outcomes import Outcomes
from experimenter.outcomes.tests import mock_valid_outcomes

CREATE_EXPERIMENT_MUTATION = """\
mutation($input: ExperimentInput!) {
    createExperiment(input: $input) {
        nimbusExperiment {
            slug
        }
        message
    }
}
"""


UPDATE_EXPERIMENT_MUTATION = """\
mutation($input: ExperimentInput!) {
    updateExperiment(input: $input) {
        message
    }
}
"""


END_EXPERIMENT_MUTATION = """\
mutation ($input: ExperimentIdInput!){
  endExperiment(input: $input){
    message
  }
}
"""


@mock_valid_outcomes
class TestMutations(GraphQLTestCase):
    GRAPHQL_URL = reverse("nimbus-api-graphql")
    maxDiff = None

    def setUp(self):
        Outcomes.clear_cache()

    def test_create_experiment(self):
        user_email = "user@example.com"
        response = self.query(
            CREATE_EXPERIMENT_MUTATION,
            variables={
                "input": {
                    "name": "Test 1234",
                    "hypothesis": "Test hypothesis",
                    "application": NimbusExperiment.Application.DESKTOP.name,
                }
            },
            headers={settings.OPENIDC_EMAIL_HEADER: user_email},
        )
        self.assertEqual(response.status_code, 200)
        content = json.loads(response.content)
        result = content["data"]["createExperiment"]
        self.assertEqual(result["message"], "success")

        experiment = NimbusExperiment.objects.first()
        self.assertEqual(experiment.name, "Test 1234")
        self.assertEqual(experiment.slug, "test-1234")
        self.assertEqual(experiment.application, NimbusExperiment.Application.DESKTOP)

    def test_create_experiment_error(self):
        user_email = "user@example.com"
        long_name = "test" * 1000
        response = self.query(
            CREATE_EXPERIMENT_MUTATION,
            variables={
                "input": {
                    "name": long_name,
                    "hypothesis": "Test hypothesis",
                    "application": NimbusExperiment.Application.DESKTOP.name,
                }
            },
            headers={settings.OPENIDC_EMAIL_HEADER: user_email},
        )
        self.assertEqual(response.status_code, 200)
        content = json.loads(response.content)
        result = content["data"]["createExperiment"]
        self.assertEqual(
            result["message"],
            {"name": ["Ensure this field has no more than 255 characters."]},
        )

    def test_update_experiment_overview(self):
        user_email = "user@example.com"
        experiment = NimbusExperimentFactory.create(
            status=NimbusExperiment.Status.DRAFT,
            slug="old slug",
            name="old name",
            hypothesis="old hypothesis",
            public_description="old public description",
        )
        response = self.query(
            UPDATE_EXPERIMENT_MUTATION,
            variables={
                "input": {
                    "id": experiment.id,
                    "name": "new name",
                    "hypothesis": "new hypothesis",
                    "publicDescription": "new public description",
                    "riskMitigationLink": "https://example.com/risk",
                }
            },
            headers={settings.OPENIDC_EMAIL_HEADER: user_email},
        )
        self.assertEqual(response.status_code, 200, response.content)
        content = json.loads(response.content)
        result = content["data"]["updateExperiment"]
        self.assertEqual(result["message"], "success")

        experiment = NimbusExperiment.objects.first()
        self.assertEqual(experiment.slug, "old slug")
        self.assertEqual(experiment.name, "new name")
        self.assertEqual(experiment.hypothesis, "new hypothesis")
        self.assertEqual(experiment.public_description, "new public description")
        self.assertEqual(experiment.risk_mitigation_link, "https://example.com/risk")

    def test_update_experiment_error(self):
        user_email = "user@example.com"
        long_name = "test" * 1000
        experiment = NimbusExperimentFactory.create(status=NimbusExperiment.Status.DRAFT)
        response = self.query(
            UPDATE_EXPERIMENT_MUTATION,
            variables={
                "input": {
                    "id": experiment.id,
                    "name": long_name,
                    "hypothesis": "new hypothesis",
                    "riskMitigationLink": "i like pie",
                }
            },
            headers={settings.OPENIDC_EMAIL_HEADER: user_email},
        )
        self.assertEqual(response.status_code, 200)
        content = json.loads(response.content)
        result = content["data"]["updateExperiment"]
        self.assertEqual(
            result["message"],
            {
                "name": ["Ensure this field has no more than 255 characters."],
                "risk_mitigation_link": ["Enter a valid URL."],
            },
        )

    def test_update_experiment_documentation_links(self):
        user_email = "user@example.com"
        experiment = NimbusExperimentFactory.create(status=NimbusExperiment.Status.DRAFT)
        experiment_id = experiment.id

        documentation_links = [
            {
                "title": NimbusExperiment.DocumentationLink.DS_JIRA.value,
                "link": "https://example.com/bar",
            },
            {
                "title": NimbusExperiment.DocumentationLink.ENG_TICKET.value,
                "link": "https://example.com/quux",
            },
            {
                "title": NimbusExperiment.DocumentationLink.DESIGN_DOC.value,
                "link": "https://example.com/plotz",
            },
        ]

        response = self.query(
            UPDATE_EXPERIMENT_MUTATION,
            variables={
                "input": {
                    "id": experiment.id,
                    "documentationLinks": documentation_links,
                }
            },
            headers={settings.OPENIDC_EMAIL_HEADER: user_email},
        )

        self.assertEqual(response.status_code, 200)

        experiment = NimbusExperiment.objects.get(id=experiment_id)
        experiment_links = experiment.documentation_links.all()
        for key in (
            "title",
            "link",
        ):
            self.assertEqual(
                {b[key] for b in documentation_links},
                {getattr(b, key) for b in experiment_links},
            )

    def test_does_not_delete_branches_when_other_fields_specified(self):
        user_email = "user@example.com"
        experiment = NimbusExperimentFactory.create_with_status(
            NimbusExperiment.Status.DRAFT
        )
        branch_count = experiment.branches.count()
        response = self.query(
            UPDATE_EXPERIMENT_MUTATION,
            variables={
                "input": {
                    "id": experiment.id,
                    "name": "new name",
                    "hypothesis": "new hypothesis",
                    "publicDescription": "new public description",
                }
            },
            headers={settings.OPENIDC_EMAIL_HEADER: user_email},
        )
        self.assertEqual(response.status_code, 200, response.content)
        content = json.loads(response.content)
        result = content["data"]["updateExperiment"]
        self.assertEqual(result["message"], "success")

        experiment = NimbusExperiment.objects.first()
        self.assertEqual(experiment.branches.count(), branch_count)

    def test_does_not_clear_feature_config_when_other_fields_specified(self):
        user_email = "user@example.com"
        experiment = NimbusExperimentFactory.create_with_status(
            NimbusExperiment.Status.DRAFT
        )
        expected_feature_config = experiment.feature_config

        response = self.query(
            UPDATE_EXPERIMENT_MUTATION,
            variables={
                "input": {
                    "id": experiment.id,
                    "name": "new name",
                    "hypothesis": "new hypothesis",
                    "publicDescription": "new public description",
                }
            },
            headers={settings.OPENIDC_EMAIL_HEADER: user_email},
        )
        self.assertEqual(response.status_code, 200, response.content)
        content = json.loads(response.content)
        result = content["data"]["updateExperiment"]
        self.assertEqual(result["message"], "success")

        experiment = NimbusExperiment.objects.first()
        self.assertEqual(experiment.feature_config, expected_feature_config)

    def test_update_experiment_branches_with_feature_config(self):
        user_email = "user@example.com"
        feature = NimbusFeatureConfigFactory(schema="{}")
        experiment = NimbusExperimentFactory.create(status=NimbusExperiment.Status.DRAFT)
        experiment_id = experiment.id
        reference_branch = {"name": "control", "description": "a control", "ratio": 1}
        treatment_branches = [{"name": "treatment1", "description": "desc1", "ratio": 1}]
        response = self.query(
            UPDATE_EXPERIMENT_MUTATION,
            variables={
                "input": {
                    "id": experiment.id,
                    "featureConfigId": feature.id,
                    "referenceBranch": reference_branch,
                    "treatmentBranches": treatment_branches,
                }
            },
            headers={settings.OPENIDC_EMAIL_HEADER: user_email},
        )
        self.assertEqual(response.status_code, 200)

        experiment = NimbusExperiment.objects.get(id=experiment_id)
        self.assertEqual(experiment.feature_config, feature)
        self.assertEqual(experiment.branches.count(), 2)
        self.assertEqual(experiment.reference_branch.name, reference_branch["name"])
        treatment_branch = experiment.treatment_branches[0]
        self.assertEqual(treatment_branch.name, treatment_branches[0]["name"])

    def test_update_experiment_branches_with_feature_config_error(self):
        user_email = "user@example.com"
        experiment = NimbusExperimentFactory.create(status=NimbusExperiment.Status.DRAFT)
        reference_branch = {"name": "control", "description": "a control", "ratio": 1}
        treatment_branches = [{"name": "treatment1", "description": "desc1", "ratio": 1}]
        # The NimbusExperimentFactory always creates a single feature config.
        self.assertEqual(NimbusFeatureConfig.objects.count(), 1)
        response = self.query(
            UPDATE_EXPERIMENT_MUTATION,
            variables={
                "input": {
                    "id": experiment.id,
                    "featureConfigId": 2,
                    "referenceBranch": reference_branch,
                    "treatmentBranches": treatment_branches,
                }
            },
            headers={settings.OPENIDC_EMAIL_HEADER: user_email},
        )
        self.assertEqual(response.status_code, 200)
        content = json.loads(response.content)
        result = content["data"]["updateExperiment"]
        self.assertEqual(
            result["message"],
            {"feature_config": ['Invalid pk "2" - object does not exist.']},
        )

    def test_update_experiment_outcomes(self):
        user_email = "user@example.com"
        experiment = NimbusExperimentFactory.create(
            status=NimbusExperiment.Status.DRAFT,
            application=NimbusExperiment.Application.DESKTOP,
            primary_outcomes=[],
            secondary_outcomes=[],
        )
        outcomes = [
            o.slug for o in Outcomes.by_application(NimbusExperiment.Application.DESKTOP)
        ]
        primary_outcomes = outcomes[: NimbusExperiment.MAX_PRIMARY_OUTCOMES]
        secondary_outcomes = outcomes[NimbusExperiment.MAX_PRIMARY_OUTCOMES :]

        response = self.query(
            UPDATE_EXPERIMENT_MUTATION,
            variables={
                "input": {
                    "id": experiment.id,
                    "primaryOutcomes": primary_outcomes,
                    "secondaryOutcomes": secondary_outcomes,
                }
            },
            headers={settings.OPENIDC_EMAIL_HEADER: user_email},
        )
        self.assertEqual(response.status_code, 200, response.content)

        experiment = NimbusExperiment.objects.get(slug=experiment.slug)
        self.assertEqual(experiment.primary_outcomes, primary_outcomes)
        self.assertEqual(experiment.secondary_outcomes, secondary_outcomes)

    def test_update_experiment_outcomes_error(self):
        user_email = "user@example.com"
        experiment = NimbusExperimentFactory.create(
            status=NimbusExperiment.Status.DRAFT,
            application=NimbusExperiment.Application.DESKTOP,
            primary_outcomes=[],
            secondary_outcomes=[],
        )

        response = self.query(
            UPDATE_EXPERIMENT_MUTATION,
            variables={
                "input": {
                    "id": experiment.id,
                    "primaryOutcomes": ["invalid-outcome"],
                    "secondaryOutcomes": ["invalid-outcome"],
                }
            },
            headers={settings.OPENIDC_EMAIL_HEADER: user_email},
        )
        self.assertEqual(response.status_code, 200, response.content)
        content = json.loads(response.content)
        result = content["data"]["updateExperiment"]
        self.assertEqual(
            result["message"],
            {
                "primary_outcomes": [
                    "Invalid choices for primary outcomes: {'invalid-outcome'}"
                ],
                "secondary_outcomes": [
                    "Invalid choices for secondary outcomes: {'invalid-outcome'}"
                ],
            },
        )

    def test_update_experiment_audience(self):
        user_email = "user@example.com"
        experiment = NimbusExperimentFactory.create(
            status=NimbusExperiment.Status.DRAFT,
            channel=NimbusExperiment.Channel.NO_CHANNEL,
            application=NimbusConstants.Application.DESKTOP,
            firefox_min_version=NimbusExperiment.Version.NO_VERSION,
            population_percent=0.0,
            proposed_duration=0,
            proposed_enrollment=0,
            targeting_config_slug=NimbusExperiment.TargetingConfig.NO_TARGETING,
            total_enrolled_clients=0,
        )
        self.query(
            UPDATE_EXPERIMENT_MUTATION,
            variables={
                "input": {
                    "id": experiment.id,
                    "channel": NimbusConstants.Channel.BETA.name,
                    "firefoxMinVersion": NimbusConstants.Version.FIREFOX_83.name,
                    "populationPercent": "10",
                    "proposedDuration": 42,
                    "proposedEnrollment": 120,
                    "targetingConfigSlug": (
                        NimbusConstants.TargetingConfig.ALL_ENGLISH.name
                    ),
                    "totalEnrolledClients": 100,
                }
            },
            headers={settings.OPENIDC_EMAIL_HEADER: user_email},
        )

        experiment = NimbusExperiment.objects.get(id=experiment.id)
        self.assertEqual(experiment.channel, NimbusConstants.Channel.BETA.value)
        self.assertEqual(
            experiment.firefox_min_version, NimbusConstants.Version.FIREFOX_83.value
        )
        self.assertEqual(experiment.population_percent, 10.0)
        self.assertEqual(experiment.proposed_duration, 42)
        self.assertEqual(experiment.proposed_enrollment, 120)
        self.assertEqual(
            experiment.targeting_config_slug,
            NimbusConstants.TargetingConfig.ALL_ENGLISH.value,
        )
        self.assertEqual(experiment.total_enrolled_clients, 100)

    def test_update_experiment_audience_error(self):
        user_email = "user@example.com"
        experiment = NimbusExperimentFactory.create(
            status=NimbusExperiment.Status.DRAFT,
            channel=NimbusExperiment.Channel.NO_CHANNEL,
            firefox_min_version=NimbusExperiment.Channel.NO_CHANNEL,
            population_percent=0.0,
            proposed_duration=0,
            proposed_enrollment=0,
            targeting_config_slug=NimbusExperiment.TargetingConfig.NO_TARGETING,
            total_enrolled_clients=0,
        )
        response = self.query(
            UPDATE_EXPERIMENT_MUTATION,
            variables={
                "input": {
                    "id": experiment.id,
                    "populationPercent": "10.23471",
                }
            },
            headers={settings.OPENIDC_EMAIL_HEADER: user_email},
        )
        self.assertEqual(response.status_code, 200)
        content = json.loads(response.content)
        result = content["data"]["updateExperiment"]
        self.assertEqual(
            result["message"],
            {
                "population_percent": [
                    "Ensure that there are no more than 4 decimal places."
                ]
            },
        )

    def test_update_experiment_status(self):
        user_email = "user@example.com"
        experiment = NimbusExperimentFactory.create(
            status=NimbusExperiment.Status.DRAFT,
        )
        response = self.query(
            UPDATE_EXPERIMENT_MUTATION,
            variables={
                "input": {
                    "id": experiment.id,
                    "status": NimbusExperiment.Status.REVIEW.name,
                }
            },
            headers={settings.OPENIDC_EMAIL_HEADER: user_email},
        )
        self.assertEqual(response.status_code, 200)

        experiment = NimbusExperiment.objects.get(id=experiment.id)
        self.assertEqual(experiment.status, NimbusExperiment.Status.REVIEW)

    def test_update_experiment_status_error(self):
        user_email = "user@example.com"
        experiment = NimbusExperimentFactory.create(
            status=NimbusExperiment.Status.ACCEPTED,
        )
        response = self.query(
            UPDATE_EXPERIMENT_MUTATION,
            variables={
                "input": {
                    "id": experiment.id,
                    "status": NimbusExperiment.Status.REVIEW.name,
                }
            },
            headers={settings.OPENIDC_EMAIL_HEADER: user_email},
        )
        self.assertEqual(response.status_code, 200, response.content)
        content = json.loads(response.content)
        result = content["data"]["updateExperiment"]
        self.assertEqual(
            result["message"],
            {
                "status": [
                    "Nimbus Experiment status cannot transition from Accepted to Review."
                ]
            },
        )

    def test_end_experiment_in_kinto(self):
        user_email = "user@example.com"
        experiment = NimbusExperimentFactory.create(
            status=NimbusExperiment.Status.LIVE,
        )
        response = self.query(
            END_EXPERIMENT_MUTATION,
            variables={
                "input": {
                    "id": experiment.id,
                }
            },
            headers={settings.OPENIDC_EMAIL_HEADER: user_email},
        )
        self.assertEqual(response.status_code, 200, response.content)

        experiment = NimbusExperiment.objects.get(id=experiment.id)
        self.assertEqual(experiment.is_end_requested, True)
        latest_change = experiment.changes.order_by("-changed_on").first()
        self.assertEqual(latest_change.experiment_data["is_end_requested"], True)

    def test_end_experiment_in_kinto_fails_with_nonlive_status(self):
        user_email = "user@example.com"
        experiment = NimbusExperimentFactory.create(
            status=NimbusExperiment.Status.DRAFT,
        )
        response = self.query(
            END_EXPERIMENT_MUTATION,
            variables={
                "input": {
                    "id": experiment.id,
                }
            },
            headers={settings.OPENIDC_EMAIL_HEADER: user_email},
        )
        self.assertEqual(response.status_code, 200, response.content)

        content = json.loads(response.content)
        result = content["data"]["endExperiment"]
        self.assertEqual(
            result["message"],
            "Nimbus Experiment has status 'Draft', but can only "
            "be ended when set to 'Live'.",
        )

        experiment = NimbusExperiment.objects.get(id=experiment.id)
        self.assertEqual(experiment.is_end_requested, False)
