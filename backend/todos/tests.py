"""Tests for the todos app: CRUD, auth gating, ownership isolation, validation."""
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase

from todos.models import Todo

LIST_URL = '/api/todos/'


def detail_url(pk):
    return f'/api/todos/{pk}/'


class AuthRequiredTests(APITestCase):
    def test_list_requires_authentication(self):
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_requires_authentication(self):
        resp = self.client.post(LIST_URL, {'title': 'x'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class TodoCrudTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='alice', password='sup3rSecret!'
        )
        self.client.force_authenticate(self.user)

    def test_create_sets_owner_and_defaults_completed_false(self):
        resp = self.client.post(
            LIST_URL,
            {'title': 'Buy milk', 'description': 'skim'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['title'], 'Buy milk')
        self.assertFalse(resp.data['completed'])
        todo = Todo.objects.get(pk=resp.data['id'])
        self.assertEqual(todo.owner, self.user)

    def test_list_returns_only_own_todos(self):
        Todo.objects.create(owner=self.user, title='mine')
        other = User.objects.create_user(username='bob', password='sup3rSecret!')
        Todo.objects.create(owner=other, title='theirs')

        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        titles = [t['title'] for t in resp.data['results']]
        self.assertEqual(titles, ['mine'])

    def test_retrieve_own_todo(self):
        todo = Todo.objects.create(owner=self.user, title='mine')
        resp = self.client.get(detail_url(todo.pk))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['title'], 'mine')

    def test_patch_toggles_completed(self):
        todo = Todo.objects.create(owner=self.user, title='mine')
        resp = self.client.patch(
            detail_url(todo.pk), {'completed': True}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        todo.refresh_from_db()
        self.assertTrue(todo.completed)

    def test_patch_edits_title(self):
        todo = Todo.objects.create(owner=self.user, title='old')
        resp = self.client.patch(
            detail_url(todo.pk), {'title': 'new'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        todo.refresh_from_db()
        self.assertEqual(todo.title, 'new')

    def test_delete_own_todo(self):
        todo = Todo.objects.create(owner=self.user, title='mine')
        resp = self.client.delete(detail_url(todo.pk))
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Todo.objects.filter(pk=todo.pk).exists())


class ValidationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='alice', password='sup3rSecret!'
        )
        self.client.force_authenticate(self.user)

    def test_empty_title_is_rejected(self):
        resp = self.client.post(LIST_URL, {'title': ''}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_title_is_rejected(self):
        resp = self.client.post(LIST_URL, {'description': 'x'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_too_long_title_is_rejected(self):
        resp = self.client.post(
            LIST_URL, {'title': 'a' * 256}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class OwnershipIsolationTests(APITestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username='alice', password='sup3rSecret!'
        )
        self.bob = User.objects.create_user(
            username='bob', password='sup3rSecret!'
        )
        self.bob_todo = Todo.objects.create(owner=self.bob, title='bob secret')
        self.client.force_authenticate(self.alice)

    def test_cannot_retrieve_other_users_todo_returns_404(self):
        resp = self.client.get(detail_url(self.bob_todo.pk))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_patch_other_users_todo_returns_404(self):
        resp = self.client.patch(
            detail_url(self.bob_todo.pk), {'title': 'hacked'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.bob_todo.refresh_from_db()
        self.assertEqual(self.bob_todo.title, 'bob secret')

    def test_cannot_delete_other_users_todo_returns_404(self):
        resp = self.client.delete(detail_url(self.bob_todo.pk))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Todo.objects.filter(pk=self.bob_todo.pk).exists())
