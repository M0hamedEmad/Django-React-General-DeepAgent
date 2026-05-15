from django.http import HttpResponse
from django.urls import path, re_path

from deep_agent_app import views

urlpatterns = [
    path("chat/", views.chat_page, name="chat-page"),
    # A thread's own address. Ids are uuid4().hex; the slash is optional so a pasted link works either way.
    re_path(
        r"^chat/(?P<thread_id>[0-9a-f]{32})/?$", views.chat_page, name="chat-thread"
    ),
    path(
        "favicon.ico", lambda request: HttpResponse(status=204)
    ),  # browsers ask; keep the log clean
    path("api/chat/", views.ChatView.as_view(), name="chat"),
    path("api/config/", views.ConfigView.as_view(), name="config"),
    path("api/runtime/", views.RuntimeView.as_view(), name="runtime"),
    path("api/threads/", views.ThreadListView.as_view(), name="thread-list"),
    path("api/threads/<str:thread_id>/", views.ThreadView.as_view(), name="thread"),
    path(
        "api/threads/<str:thread_id>/messages/",
        views.ThreadMessagesView.as_view(),
        name="thread-messages",
    ),
    path(
        "api/threads/<str:thread_id>/messages/<str:message_id>/",
        views.ThreadMessageView.as_view(),
        name="thread-message",
    ),
]
