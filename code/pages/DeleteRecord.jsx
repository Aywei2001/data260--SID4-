import React, { useEffect, useState } from "react";
import { Routes, Route, useNavigate } from "react-router-dom";

function DeleteRecord({onDeleteRecord}) {
    const navigate = useNavigate();
    const location = useLocation();
    const initialId = location.state?.record || '';
    const [recordId, setRecordId] = useState(initialId);
    const [error, setError] = useState('');

    const handleDelete = (e) => {
        e.preventDefault;

        const updateData = {name, description};

        fetch('http://localhost:8080/records', {
            method: 'GET',
            headers: {'Content-Type': 'application/json'},
            credentials: 'include',
            body: JSON.stringify(updateData),
        })
        .then((response) => {
            if (response.status == 401){
                throw new Error('Log in Required')
            }
            if (!response.ok) {
                throw new Error('Unable to delete record');
            }
            return response.json();
        })
        .then((data) => {
            if (onDeleteRecord) {
                onDeleteRecord(recordId);
            }
            navigate('/');
        })
        .catch((err) => {
            setError(err.message);
        });
    };

    return (
        <div>
            <form onSubmit = {handleDelete}>
                <div>
                    <label htmlFor="delete-id">Record ID to Delete: </label>
                    <input id="delete-id" type="number" value={recordId} onChange={(e) => setRecordId(e.target.value)} required />
                </div>
                <button type="submit">Delete Record</button>
            </form>
        </div>
    )

}