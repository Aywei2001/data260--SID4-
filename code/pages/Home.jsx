import React, { useEffect, useState } from "react";
import { Routes, Route, useNavigate } from "react-router-dom";

function Home() {
    const [records, setRecords] = useState([]);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        fetch('http://localhost:8080/records', {
            method: 'GET',
            headers: {'Content-Type': 'application/json'},
            credentials: 'include',
        })
        .then((response) => {
            if (response.status == 401) {
                throw new Error('Login Required');
            }
            if (!response.ok) {
                throw new Error('Unable to get Records');
            }
            return response.json();
        })
        .then((data) => {
            setRecords(data.records);
            setLoading(false);
        })
        .catch((err) => {
            setError(err.message);
            setLoading(false);
        })
    }, []);

    if (loading) return <div>Loading your records</div>

    if (error == 'Login Required') return <div>Error: {error}</div>

    return(
        <div>
            <h1>Grocery Recall Records</h1>
            {records.length == 0 ? (
                <p>No records found</p>
            ): (
                <ul>
                    {records.map((item) => (
                        <li key = {item.id}>
                            {item.name} : {item.description}
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}