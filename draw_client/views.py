from django.shortcuts import render

def home(request):
    """
    Home page view for DRAW v2.0 application
    """
    return render(request, 'home.html')
