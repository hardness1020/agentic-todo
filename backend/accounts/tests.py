"""Tests for the accounts app: registration + JWT token issuance."""
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase

REGISTER_URL = '/api/auth/register'
TOKEN_URL = '/api/auth/token'


class RegistrationTests(APITestCase):
    def test_register_creates_user_and_omits_password(self):
        resp = self.client.post(
            REGISTER_URL,
            {'username': 'alice', 'password': 'sup3rSecret!'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(username='alice').exists())
        # Password (raw or hash) must never be returned.
        self.assertNotIn('password', resp.data)

    def test_register_persists_salted_hash_not_plaintext(self):
        self.client.post(
            REGISTER_URL,
            {'username': 'bob', 'password': 'sup3rSecret!'},
            format='json',
        )
        user = User.objects.get(username='bob')
        self.assertNotEqual(user.password, 'sup3rSecret!')
        self.assertTrue(user.check_password('sup3rSecret!'))

    def test_register_duplicate_username_is_rejected(self):
        User.objects.create_user(username='alice', password='sup3rSecret!')
        resp = self.client.post(
            REGISTER_URL,
            {'username': 'alice', 'password': 'anotherP4ss!'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_missing_password_is_rejected(self):
        resp = self.client.post(
            REGISTER_URL, {'username': 'alice'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_too_short_password_is_rejected(self):
        resp = self.client.post(
            REGISTER_URL,
            {'username': 'alice', 'password': 'x'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class TokenTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='alice', password='sup3rSecret!'
        )

    def test_obtain_token_with_valid_credentials(self):
        resp = self.client.post(
            TOKEN_URL,
            {'username': 'alice', 'password': 'sup3rSecret!'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('access', resp.data)

    def test_obtain_token_with_bad_credentials_returns_401(self):
        resp = self.client.post(
            TOKEN_URL,
            {'username': 'alice', 'password': 'wrong'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
