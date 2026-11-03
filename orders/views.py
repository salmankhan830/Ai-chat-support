from django.shortcuts import render,get_object_or_404
from .models import Order,RefundRequest
from django.contrib.auth.decorators import login_required

from support.models import Conversation

@login_required
def orders_list(request):
    order=Order.objects.filter(user=request.user)
    context={
        'orders':order
    }
    return render(request,'orders_list.html', context)


def order_details(request, order_id):
    order=get_object_or_404(Order,id=order_id, user=request.user)
    refunds=RefundRequest.objects.filter(order=order)

    try:
        conversation = Conversation.objects.get(user=request.user, order=order)
        previous_messages = conversation.messages.order_by("created_at")
    except Conversation.DoesNotExist:
        conversation = None
        previous_messages = []
        
    context={
        'order':order,
        'refunds':refunds
    }
    return render(request,'order_detail.html', context)