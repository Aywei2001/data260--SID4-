import React, { useEffect, useState } from "react";
import { Routes, Route, useNavigate } from "react-router-dom";

function CreateRecord({onAddRecord}) {
    const [name, setName] = useState('');
    const [error, setError] = useState('');
    const [description, setDescription] = useState('');
    const navigate = useNavigate();

    const handleSubmit = (e) => {
        e.preventDefault;

        const newRecordData = {name, description};

        fetch('http://localhost:8080/records', {
            method: 'GET',
            headers: {'Content-Type': 'application/json'},
            credentials: 'include',
            body: JSON.stringify(newRecordData),
        })
        .then((response) => {
            if (response.status == 401){
                throw new Error('Log in Required')
            }
            if (!response.ok) {
                throw new Error('Unable to get record');
            }
            return response.json();
        })
        .then((data) => {
            if (onAddRecord) {
                onAddRecord({id : data.id, ...newRecordData});
            }
            navigate('/');
        })
        .catch((err) => {
            setError(err.message);
        });
    };

    return (
        <div style={{ padding: '20px' }}>
        <h2>Add New Record</h2>
        {error && <p style={{ color: 'red' }}>{error}</p>}
        
        <form onSubmit={handleSubmit}>
            <div>
            <label htmlFor="name">Primary Field: </label>
            <input id="name" type="text" value={name} onChange={(e) => setName(e.target.value)} required />
            </div>

            <div>
            <label htmlFor="description">Secondary Field: </label>
            <input id="description" type="text" value={description} onChange={(e) => setDescription(e.target.value)} required />
            </div>

            <button type="submit">Create Record</button>
        </form>
        </div>
    );

}

export default CreateRecord;