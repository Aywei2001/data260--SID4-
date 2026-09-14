
// Arrow function to verify there are more than 25 characters
// This should trigger an error state
const validateFormSubmission = () => {
    const confirmInput = document.getElementById('content');
    const value = confirmInput ? confirmInput.value.trim() : '';
    if (value.length <= 25){
        alert('Must be longer than 25 characters');

        // other states are set to inactive when error state becomes active
        document.getElementById('emptyState').classList.remove('active');
        document.getElementById('loadingState').classList.remove('active');
        document.getElementById('successState').classList.remove('active');
        const errorState = document.getElementById('errorState');

        // error state then will become active
        // error message is displayed
        document.getElementById('errorMessage').textContent = 'Must be longer than 25 characters'
        errorState.classList.add('active');

        return false
    }
    return true
};


// Arrow function to check if the terms and conditions are validated
// This should trigger an error state
const validateTermsandConditions = () => {
    const checkTerms = document.getElementById('acceptTerms');
    const confirmCheck = checkTerms ? checkTerms.checked : false;
    if (!confirmCheck){
        alert('Please accept Terms and Conditions');
        
        // other states are set to inactive when error state becomes active
        document.getElementById('emptyState').classList.remove('active');
        document.getElementById('loadingState').classList.remove('active');
        document.getElementById('successState').classList.remove('active');
        const errorState = document.getElementById('errorState');

        // error state then will become active
        // error message is displayed
        document.getElementById('errorMessage').textContent = 'Please accept Terms and Conditions'
        errorState.classList.add('active');

        return false
    }
    return true
};

const Submission_Count = () => {
    let count = 0;
    return () => {
        count++;
        return count;
    }
};

const get_total_submissions  = Submission_Count();

// Event listener for all actions taken during form submission
document.getElementById('domainForm').addEventListener('submit', (event) => {
    event.preventDefault();

    const validateContent = validateFormSubmission();
    const validateTerms = validateTermsandConditions();

    // stop form from submitting if neither is validated
    if (!validateContent || !validateTerms) {
        event.preventDefault();
        return;
    }


    //  try and except for loading state to check if submission is successful or not
    try {
        // go into loading state after submitting form
        document.getElementById('emptyState').classList.remove('active');
        document.getElementById('errorState').classList.remove('active');
        document.getElementById('successState').classList.remove('active');
        document.getElementById('loadingState').classList.add('active');

        const getForm_Feedback = {
            primary : document.getElementById("sid4").value,
            secondary : document.getElementById("portBase").value,
            email : document.getElementById("prefix").value,
            content : document.getElementById("content").value,
            domain_info : document.getElementById("domain_id").value,
        };

        // cover the submitted information into JSON format
        const jsonOutput = JSON.stringify(getForm_Feedback);
        console.log("in JSON: ", jsonOutput);
        
        // extract primary field and email from parsed object
        const parse_output = JSON.parse(jsonOutput);
        const {primary, email} = parse_output;
        console.log("Primary Field:", primary);
        console.log("Email:", email);

        // get information on the date in which the form was submitted
        const parse_update = {
            ...parse_output,
            submissionDate : new Date().toISOString()
        };

        // create submission date field
        console.log("Updates: ", parse_update);

        // create closure to track number of times form was submitted
        const form_count = get_total_submissions();
        console.log("Total number of form submissions: ",form_count);

        // display details of the the form submission by connecting to HTML
        document.getElementById('show_Output').innerHTML = `<strong>Primary Field:</strong> ${primary}
                                                            <br> <strong>Email:</strong> ${email}<br> 
                                                            <strong>Domain:</strong> ${parse_update.domain_info}<br> 
                                                            <strong>Submitted Date</strong> ${parse_update.submissionDate}<br> 
                                                            <strong>Total Submissions:</strong> ${form_count}<br>`;
        
        // connect to main.py FastAPI to send information there
        fetch('/api/users', {
            method: 'POST',
            headers: {'content type': 'application/json'},
            body: JSON.stringify({
                primary_field: primary,
                secondary_field: parse_update.domain_info
            })
        })
        .then(res => res.json())
        .then(data => console.log("", data))
        .catch(err => console.error("", err))

        // go into success state if submission is successful
        document.getElementById('loadingState').classList.remove('active');
        document.getElementById('successState').classList.add('active');

    }
    // go into error state if submission is not successful
    //  error state is treate like an exception being raised
    catch(error){
        document.getElementById('emptyState').classList.remove('active');
        document.getElementById('loadingState').classList.remove('active');
        document.getElementById('successState').classList.remove('active');
        document.getElementById('errorState').classList.add('active');
    }

});