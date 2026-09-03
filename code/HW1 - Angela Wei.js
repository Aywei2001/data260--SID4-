
// Arrow function to verify there are more than 25 characters
const validateFormSubmission = () => {
    const confirmInput = document.getElementById('content');
    const value = confirmInput ? confirmInput.value.trim() : '';
    if (value.length <= 25){
        alert('Must be longer than 25 characters');
        return false
    }
    return true
};


// Arrow function to check if the terms and conditions are validated
const validateTermsandConditions = () => {
    const checkTerms = document.getElementById('acceptTerms');
    const confirmCheck = checkTerms ? checkTerms.checked : false;
    if (!confirmCheck){
        alert('Please accept Terms and Conditions');
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
    const validateContent = validateFormSubmission();
    const validateTerms = validateTermsandConditions();

    // stop form from submitting if neither is validated
    if (!validateContent || !validateTerms) {
        event.preventDefault();
        return;
    }

    event.preventDefault();

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
});