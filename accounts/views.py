from django.contrib import messages
from django.contrib.auth import login
from django.db import IntegrityError
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect
from django.views.generic import FormView
from django.urls import reverse_lazy

from .forms import LoginForm, SignupForm
from .models import Membership


class SignupView(FormView):
    template_name = "accounts/signup.html"
    form_class = SignupForm
    success_url = reverse_lazy("documents:dashboard")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and Membership.objects.filter(user=request.user).exists():
            return redirect("documents:dashboard")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            user = form.save()
        except IntegrityError:
            form.add_error("email", "A workspace already exists for this email.")
            return self.form_invalid(form)
        login(self.request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(self.request, "Workspace created. Welcome to CertDesk.")
        return super().form_valid(form)


class AppLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        remember_me = form.cleaned_data.get("remember_me")
        if not remember_me:
            self.request.session.set_expiry(0)  # Session expires when browser closes
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("documents:dashboard")


@login_required
def logout_view(request):
    from django.contrib.auth import logout

    logout(request)
    messages.info(request, "You have been signed out.")
    return redirect("core:landing")
