1) what you used an AI assistant for and what
you did yourself
AI was used in this assignment to debug code and as a guide to help me look up resources on what to use in the code

2) one AI-produced output that was wrong/unsuitable, or one thing you independently verified
I unknowingly utilized some outdated syntax for the Starlette SessionMiddleware Template Response from examples I have looked at while figuring out how to write the code for the routes for the different web pages. While Google Gemini was able to immediately point out what code will cause the files to not run it missed the outdated syntax.

3) how you detected the problem or verified the result
When I first tested the code in the Localhost, none of my pages showed up despite the Python files successfully running. I was able to use the messages from the Terminal to figure out which lines needed to be fixed and looked for the correct syntax.

4) what you changed and why it works now.
The syntax was originally:
return templates.TemplateResponse(
    "hw3_home-index.html",
    {
        "request": request,  
        "user": user
    }
)

Which did not work

Changing it to:
return templates.TemplateResponse(
    request=request,
    name="hw3_home-index.html",
    context={"user": user}
)
