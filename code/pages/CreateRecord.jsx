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
        <router>
            <routes>
                <Route path="/" element={<Home />} />
                <Route path="/login" element={<Login />} />
                {/* Render CreateRecord on '/create' */}
                <Route path="/create" element={<CreateRecord onAddRecord={handleAddRecord} />} />
            </routes>
        </router>
    );

}

export default CreateRecord;