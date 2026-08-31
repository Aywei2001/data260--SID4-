
// Arrow function to verify there are more than 25 characters
const validateFormSubmission = () => {
    const confirmInput = document.getElementById('content');
    const value = confirmInput ? confirmInput.value.trim() : '';
    if (value.length <= 25){
        alert('Must be longer that 25 characters');
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


// Event listener for all actions taken during form submission
document.getElementById().addEventListener('submit', (event) => {
    const validateContent = validateFormSubmission();
    const validateTerms = validateTermsandConditions();

    // stop form from submitting if neither is validated
    if (!validateContent || !validateTerms) {
        event.preventDefault();
        return;
    }

    event.preventDefault();

    const primary = document.getElementById("sid4").value;
    const secondary = document.getElementById("portBase").value;
    const email = document.getElementById("prefix").value;
    const content = document.getElementById("content").value;
    const domain_info = document.getElementById("domain_id").value;

    const getForm_Feedback = {primary, secondary, email, content, domain_info};

    // cover the submitted information into JSON format
    const form = document.JSON.stringify(getFeedback);

    // get information on the date in which the form was submitted
    const submit_date = new Date();
    const record_date = submit_date.toISOString();

    // extract primary field and email from parsed object
    const parseObject = JSON.parse(getForm_Feedback);

    // create submission date field
    const format_date = {DateSubmitted: record_date};

    // create closure to track number of times form was submitted
    const form_count = Number(form_count) + 1;
    localStorage.setItem("Count_of_Submission", form_count);
});