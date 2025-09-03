import json
from django import template
from django.utils import timezone
from datetime import timedelta

register = template.Library()

@register.filter
def parse_json(value):
    """Parse JSON string into Python object"""
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []

@register.filter
def mul(value, arg):
    """Multiply the value by the argument"""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
def div(value, arg):
    """Divide the value by the argument"""
    try:
        if float(arg) == 0:
            return 0
        return float(value) / float(arg)
    except (ValueError, TypeError, ZeroDivisionError):
        return 0

@register.filter
def add_filter(value, arg):
    """Add the argument to the value"""
    try:
        return float(value) + float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
def percentage(value, total):
    """Calculate percentage"""
    try:
        if float(total) == 0:
            return 0
        return (float(value) / float(total)) * 100
    except (ValueError, TypeError, ZeroDivisionError):
        return 0

@register.filter
def add_class(value):
    """Get the class/type of the value"""
    return str(type(value).__name__)

@register.filter
def is_recently_created(created_at, hours=2):
    """Check if the object was created within the specified hours (default 2 hours)"""
    try:
        if not created_at:
            return False
        now = timezone.now()
        cutoff = now - timedelta(hours=int(hours))
        return created_at > cutoff
    except (ValueError, TypeError):
        return False
