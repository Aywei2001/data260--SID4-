{
  "technique": "Sentence-window",
  "query": "What food recalls are related to contamination or undeclared allergens?",
  "query_vector_shape": [
    384
  ],
  "doc_vectors_shape": [
    3,
    384
  ],
  "results": [
    {
      "rank": 1,
      "store_score": 0.5989,
      "cosine_sim": 0.5433,
      "chunk_len": 516,
      "preview": "Recalling Firm: Oasis Brands, Inc Product Description: Crema GuateLinda (Guatemalan Style Cream) in individually soft poly/plastic bags labeled in part: Lacteos"
    },
    {
      "rank": 2,
      "store_score": 0.5825,
      "cosine_sim": 0.6924,
      "chunk_len": 103,
      "preview": "Tipp City, OH 45371 Reason for Recall: The firm stated that the product contains undeclared allergens. "
    },
    {
      "rank": 3,
      "store_score": 0.5804,
      "cosine_sim": 0.5355,
      "chunk_len": 218,
      "preview": "Product Description: \"Alcapurria Jueyes\" (Crab-filled fritters) - Food Service Reason for Recall: Undeclared allergens: wheat, soy, crustacean shellfish (crab),"
    }
  ]
}

{
  "technique": "Token",
  "query": "What food recalls are related to contamination or undeclared allergens?",
  "query_vector_shape": [
    384
  ],
  "doc_vectors_shape": [
    3,
    384
  ],
  "results": [
    {
      "rank": 1,
      "store_score": 0.6731,
      "cosine_sim": 0.785,
      "chunk_len": 67,
      "preview": "- Food Service Reason for Recall: Undeclared allergens: wheat, soy,"
    },
    {
      "rank": 2,
      "store_score": 0.6265,
      "cosine_sim": 0.5298,
      "chunk_len": 54,
      "preview": "Undeclared allergens: wheat, soy, crustacean shellfish"
    },
    {
      "rank": 3,
      "store_score": 0.6253,
      "cosine_sim": 0.5343,
      "chunk_len": 86,
      "preview": "the product contains undeclared allergens. Classification: Class II Status: Terminated"
    }
  ]
}

{
  "technique": "Semantic",
  "query": "What food recalls are related to contamination or undeclared allergens?",
  "query_vector_shape": [
    384
  ],
  "doc_vectors_shape": [
    3,
    384
  ],
  "results": [
    {
      "rank": 1,
      "store_score": 0.6292,
      "cosine_sim": 0.6817,
      "chunk_len": 165,
      "preview": "By: Trophy Nut Co. Tipp City, OH 45371 Reason for Recall: The firm stated that the product contains undeclared allergens. Classification: Class II Status: Termi"
    },
    {
      "rank": 2,
      "store_score": 0.5897,
      "cosine_sim": 0.5577,
      "chunk_len": 749,
      "preview": "Recalling Firm: Oasis Brands, Inc Product Description: Crema GuateLinda (Guatemalan Style Cream) in individually soft poly/plastic bags labeled in part: Lacteos"
    },
    {
      "rank": 3,
      "store_score": 0.5871,
      "cosine_sim": 0.6027,
      "chunk_len": 262,
      "preview": "-Reser's Gourmet Tuna Salad packaged in 2/5-lb carton cases.  Reser's Fine Foods, Inc., Beaverton, OR.  UPC 071117855067 Reason for Recall: The recalled product"
    }
  ]
}