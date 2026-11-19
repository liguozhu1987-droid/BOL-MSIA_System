# -*- coding: utf-8 -*-
"""员工序列化器初始密码相关测试 (原 apps/users/tests.py, T05-R1 #5 迁入 tests 包)"""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.users.models import Employee
from apps.users.permissions import IsAuthenticatedEmployee
from apps.users.serializers import EmployeeSerializer


class InitialPasswordTests(SimpleTestCase):
	def test_admin_created_employee_gets_hashed_initial_password_and_change_flag(self):
		serializer = EmployeeSerializer(data={
			'username': 'new.employee',
			'name': 'New Employee',
			'initial_password': 'Start!Pass2026',
		})
		serializer.fields['username'].validators = []
		self.assertTrue(serializer.is_valid(), serializer.errors)

		with patch.object(Employee, 'save'):
			employee = serializer.save()

		self.assertTrue(employee.check_password('Start!Pass2026'))
		self.assertTrue(employee.must_change_password)

	def test_initial_password_is_required_for_admin_created_employee(self):
		serializer = EmployeeSerializer(data={
			'username': 'new.employee',
			'name': 'New Employee',
		})
		serializer.fields['username'].validators = []

		self.assertFalse(serializer.is_valid())
		self.assertIn('initial_password', serializer.errors)

	def test_admin_can_reset_existing_employee_password_and_require_change(self):
		employee = Employee(username='existing.user', name='Existing User')
		employee.set_password('Previous!Pass2026')
		serializer = EmployeeSerializer(
			instance=employee,
			data={'initial_password': 'Replacement!2026'},
			partial=True,
		)
		self.assertTrue(serializer.is_valid(), serializer.errors)

		with patch.object(Employee, 'save'):
			updated_employee = serializer.save()

		self.assertFalse(updated_employee.check_password('Previous!Pass2026'))
		self.assertTrue(updated_employee.check_password('Replacement!2026'))
		self.assertTrue(updated_employee.must_change_password)

	def test_first_login_account_is_limited_to_password_change_and_logout(self):
		permission = IsAuthenticatedEmployee()
		employee = SimpleNamespace(is_authenticated=True, must_change_password=True)

		allowed = SimpleNamespace(
			user=employee,
			resolver_match=SimpleNamespace(url_name='auth-change-password'),
			method='POST',
		)
		denied = SimpleNamespace(
			user=employee,
			resolver_match=SimpleNamespace(url_name='analytics-dashboard'),
			method='GET',
		)

		self.assertTrue(permission.has_permission(allowed, None))
		self.assertFalse(permission.has_permission(denied, None))
