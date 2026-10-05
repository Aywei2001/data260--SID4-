import React, { useEffect, useState } from "react";
import { Routes, Route, useNavigate } from "react-router-dom";

function UpdateRecord({onUpdateRecord}) {
    const navigate = useNavigate();
    const location = useLocation();
    const initialRecord = location.state?.record || {id: '', name: '', description: ''}
    const [id, setID] = useState(initialRecord.id);
    const [name, setName] = useState(initialRecord.name);
    const [description, setDescription] = useState(initialRecord.desc);
    const [error, setError] = useState('');

    const handleSubmit = (e) => {
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
                throw new Error('Unable to update record');
            }
            return response.json();
        })
        .then((data) => {
            if (onUpdateRecord) {
                onUpdateRecord({id : data.id, ...updateData});
            }
            navigate('/');
        })
        .catch((err) => {
            setError(err.message);
        });
    };

    return (
        <div>
            <form onSubmit = {handleSubmit}>
                <div>
                    <label htmlFor="record-id">Record ID: </label>
                    <input id="record-id" type="number" value={id} onChange={(e) => setId(e.target.value)} required />
                </div>
                <div>
                    <label htmlFor="update-name">Primary Field: </label>
                    <input id="update-name" type="text" value={name} onChange={(e) => setName(e.target.value)} required />
                </div>
                <div>
                    <label htmlFor="update-description">Secondary Field: </label>
                    <input id="update-description" type="text" value={description} onChange={(e) => setDescription(e.target.value)} required />
                </div>
                <button type="submit">Confirm Record Update</button>
            </form>
        </div>
    );

}

export default UpdateRecord;