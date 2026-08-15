"""Pricing module.

Deliberately smelly fixture for the Argus maintainability eval scenario.
Each smell maps to one CODE-1xx rule; the file must NOT trigger any other rule.
"""
from __future__ import annotations


def order_is_active(status):
    # CODE-105: bare-string status comparisons
    if status == "pending":
        return True
    if status == "processing":
        return True
    if status == "paid":
        return True
    return status != "cancelled"


def discount_for(user_type):
    # CODE-107: mapping if/elif chain
    if user_type == "normal":
        return 1.0
    elif user_type == "vip":
        return 0.8
    elif user_type == "svip":
        return 0.7
    elif user_type == "employee":
        return 0.5
    return 1.0


def has_admin_role(role):
    # CODE-108: or-chain membership
    if role == "admin" or role == "owner" or role == "superuser":
        return True
    return False


def apply_vip_discount(amount, is_vip):
    # CODE-104: magic number
    if is_vip:
        return amount * 0.8
    return amount


def calculate_bulk_quote(unit_price, quantity, region, is_prime):
    # CODE-101: function body > 100 non-blank lines
    total = unit_price * quantity
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    total = total + 1
    return total
