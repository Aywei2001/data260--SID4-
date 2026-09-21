from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.status import HTTP_302_FOUND
import time 


router = APIRouter()

templates = Jinja2Templates(directory="templates")

#dictionary database containing username followed by corresponding password
            #Username    Password
user_data = {"AnW_123":"f_password12345",
             "HaW_246":"s_password24680",
             "Wei0602":"g_password35912",
             "MSADI_27":"sjsu_word4814"}

#timeout after 5 minutes/300 seconds of inactivity
idle_timeout_seconds = 300

def idle_timout(request: Request):
    last_activity = request.session.get("last_activity")
    current_time = time.time()

    if last_activity:
        if current_time - last_activity > idle_timeout_seconds:
            request.session.clear()
            return True

    if "user" in request.session:
        request.session["last_activity"] = current_time

    return False


#get the homepage
@router.get("/")
def home_page(request: Request):

    #redirect back to login page if timeout happens
    if idle_timout(request):
        return RedirectResponse(
            url = "/login",
            status_code=HTTP_302_FOUND
        )

    #start the session
    user = request.session.get("user")

    #dispay the home page
    return templates.TemplateResponse(
        request = request,
        name = "hw3_home-index.html",
        context = {
            "user": user
        }
    )



#get the login page
@router.get("/login")
def login_page(request: Request, error: str = None):
    #start the session
    user = request.session.get("user")

    #stay on the dashboard as long as there is no timeout
    if user and not idle_timout(request):
        return RedirectResponse(
            url = "/dashboard",
            status_code=HTTP_302_FOUND
        )

    #display the login page
    return templates.TemplateResponse(
        request = request, 
        name = "hw3_login.html",
        context = {
            "user": user,
            "error": error
        }
    )



#get user login input
@router.post("/login")
def get_login(request: Request, user: str = Form(...), pass_wrd: str = Form(...)):
    get_cred  = user_data.get(user)

    if get_cred and get_cred == pass_wrd:
        #if the user enters a valid username and password
        #aka if the credentials already exist
        request.session["user"] = user
        request.session["last_activity"] = time.time()
        return RedirectResponse(
            #can go to user dashboard if valid
            url = "/dashboard",
            status_code=HTTP_302_FOUND
        )


    #otherwise stay on the login page
    #if there are no valid credentials
    return RedirectResponse(
        url = "/login?error=Invalid+username+or+password",
        status_code=HTTP_302_FOUND
    )



#display user dashboard after logging in
@router.get("/dashboard")
def dashboard_page(request: Request):
    #go back to login page if inactivity timeout hits
    if idle_timout(request):
        return RedirectResponse(
            url = "/login",
            status_code = HTTP_302_FOUND
        )

    #go to the dashboard page if the user is approved
    user = request.session.get("user")

    #do not display the dashboard if the user is not logged in
    if not user:
        return RedirectResponse(
            url = "/login",
            status_code = HTTP_302_FOUND
        )

    #display the dashboard if user is logged in
    return templates.TemplateResponse(
        request = request,
        name = "hw3_dashboard.html",
        context = {
            "user": user
        }
    )



#logout out of users account
@router.get("/logout")
def log_out_account(request: Request):

    #end the session upon logging out of user account
    request.session.clear()

    #redirect the user back to the homepage 
    return RedirectResponse(
        url="/",
        status_code=HTTP_302_FOUND
    )