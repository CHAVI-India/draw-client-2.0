"""
Tests for remote DICOM node export destination validation.

Covers the ability to unset the default (primary) export destination,
which was previously blocked by a "cannot remove the last primary"
validation with no way to reach a no-default state through the UI.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from dicom_server.models import RemoteDicomNode

User = get_user_model()


def _make_node(name, **kwargs):
    defaults = dict(
        host='10.0.0.1',
        port=11112,
        allow_incoming=True,
        incoming_ae_title=name.upper().replace(' ', '_')[:16],
        is_active=True,
    )
    defaults.update(kwargs)
    return RemoteDicomNode.objects.create(name=name, **defaults)


class ExportDestinationValidationTestCase(TestCase):
    """Validation rules for primary/fallback export destinations."""

    def test_can_unset_the_last_primary_export_destination(self):
        """Unchecking primary on the only primary node must succeed."""
        node = _make_node(
            'DefaultNode',
            is_export_destination=True,
            is_primary_export_destination=True,
        )

        # Simulate the UI: user unchecks "Primary Export Destination"
        node.is_primary_export_destination = False
        node.full_clean()
        node.save()

        self.assertFalse(RemoteDicomNode.objects.get(pk=node.pk).is_primary_export_destination)

    def test_can_disable_export_destination_entirely(self):
        """A node can be fully removed from export use."""
        node = _make_node(
            'DefaultNode',
            is_export_destination=True,
            is_primary_export_destination=True,
        )

        node.is_primary_export_destination = False
        node.full_clean()
        node.is_export_destination = False
        node.full_clean()
        node.save()

        node.refresh_from_db()
        self.assertFalse(node.is_export_destination)
        self.assertFalse(node.is_primary_export_destination)

    def test_can_reassign_primary_to_another_node(self):
        """The default export destination can be moved to another node."""
        old = _make_node(
            'OldDefault',
            is_export_destination=True,
            is_primary_export_destination=True,
        )
        new = _make_node('NewDefault', host='10.0.0.2')

        # Cannot be primary while another primary exists
        new.is_export_destination = True
        new.is_primary_export_destination = True
        with self.assertRaises(ValidationError):
            new.full_clean()

        # Unset the old default, then set the new one
        old.is_primary_export_destination = False
        old.full_clean()
        old.save()

        new.full_clean()
        new.save()

        self.assertFalse(
            RemoteDicomNode.objects.get(pk=old.pk).is_primary_export_destination
        )
        self.assertTrue(
            RemoteDicomNode.objects.get(pk=new.pk).is_primary_export_destination
        )

    def test_only_one_primary_export_destination(self):
        """Two nodes cannot both be the primary export destination."""
        _make_node(
            'First',
            is_export_destination=True,
            is_primary_export_destination=True,
        )
        second = _make_node(
            'Second',
            host='10.0.0.2',
            is_export_destination=True,
            is_primary_export_destination=False,
        )

        second.is_primary_export_destination = True
        with self.assertRaises(ValidationError) as ctx:
            second.full_clean()

        self.assertIn(
            'Only one remote node can be marked as the primary export destination',
            str(ctx.exception),
        )

    def test_multiple_export_destination_nodes_allowed(self):
        """A primary and fallback node can both be export destinations."""
        _make_node(
            'Primary',
            is_export_destination=True,
            is_primary_export_destination=True,
        )
        fallback = _make_node(
            'Fallback',
            host='10.0.0.2',
            is_export_destination=True,
            is_fallback_export_destination=True,
            fallback_export_destination_priority=1,
        )
        fallback.full_clean()  # must not raise
        fallback.save()

    def test_fallback_requires_existing_primary(self):
        """A fallback cannot be configured while no primary exists."""
        node = _make_node('Fallback', host='10.0.0.2')
        node.is_export_destination = True
        node.is_fallback_export_destination = True
        node.fallback_export_destination_priority = 1
        with self.assertRaises(ValidationError):
            node.full_clean()

    def test_fallback_priority_uniqueness(self):
        """Two fallback nodes cannot share the same priority."""
        _make_node(
            'Primary',
            is_export_destination=True,
            is_primary_export_destination=True,
        )
        _make_node(
            'FallbackA',
            host='10.0.0.2',
            is_export_destination=True,
            is_fallback_export_destination=True,
            fallback_export_destination_priority=1,
        )
        dup = _make_node(
            'FallbackB',
            host='10.0.0.3',
            is_export_destination=True,
            is_fallback_export_destination=True,
            fallback_export_destination_priority=1,
        )
        with self.assertRaises(ValidationError):
            dup.full_clean()


class RemoteNodeUnsetDefaultViewTestCase(TestCase):
    """The edit view allows unsetting the primary export destination."""

    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='pass12345')
        self.client.force_login(self.user)
        self.node = _make_node(
            'DefaultNode',
            is_export_destination=True,
            is_primary_export_destination=True,
        )

    def test_unsetting_primary_via_edit_form(self):
        url = reverse('dicom_server:remote_node_edit', args=[self.node.pk])
        response = self.client.post(url, {
            'name': 'DefaultNode',
            'host': '10.0.0.1',
            'port': '11112',
            'allow_incoming': 'on',
            'incoming_ae_title': 'DEFAULTNODE',
            'supports_c_find': 'on',
            'supports_c_move': 'on',
            'supports_c_get': 'on',
            'outgoing_ae_title': 'DEFAULTNODE',
            'query_retrieve_model': 'study',
            'timeout': '30',
            'max_pdu_size': '16384',
            'move_destination_ae': '',
            'is_active': 'on',
            'is_export_destination': 'on',
            # is_primary_export_destination intentionally omitted
            'is_fallback_export_destination': '',
            'fallback_export_destination_priority': '',
            'description': '',
        })

        self.assertRedirects(response, reverse('dicom_server:remote_nodes_list'))
        self.node.refresh_from_db()
        self.assertFalse(self.node.is_primary_export_destination)
        self.assertTrue(self.node.is_export_destination)
