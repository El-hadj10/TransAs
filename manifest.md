# Manifeste du Projet : TransAs (Optimisateur de Tournées de Livraison)

## 1. Vision et Objectifs
TransAs est une application mobile (APK) conçue pour optimiser le quotidien des livreurs en classant automatiquement les colis selon leurs adresses de livraison. L'objectif principal est de réduire le temps de trajet, la consommation de carburant et la fatigue mentale liée à la planification d'itinéraires, à la manière d'outils professionnels comme *Circuit*[cite: 2].

L'application repose sur une philosophie **"Offline-First & Hybride"**, exploitant au maximum la puissance de calcul locale du smartphone tout en s'appuyant sur des API ouvertes et légères pour la cartographie et le géocodage[cite: 2].

## 2. Principes Directeurs
* **Performance & Simplicité :** L'interface doit être ultra-rapide, épurée et utilisable d'une seule main (contexte de livraison intense)[cite: 2].
* **Autonomie Algorithmique :** Utilisation d'algorithmes de recherche opérationnelle (problème du voyageur de commerce - TSP) robustes, capables de tourner efficacement sur un appareil mobile[cite: 2].
* **Modularité du Code :** Séparation stricte entre l'interface utilisateur (UI), la gestion des données locales (SQLite/Fichiers) et les services distants (Géocodage, Routage)[cite: 2].
* **Délégation et Automatisation :** Le développement est découpé de manière à ce que l'agent codeur puisse exécuter et valider chaque micro-tâche de manière autonome grâce à des tests unitaires systématiques[cite: 2].

## 3. Spécifications Techniques Globales
* **Langage Principal :** Python (avec Kivy / KivyMD pour l'interface graphique multiplateforme et l'export APK)[cite: 2].
* **Moteur d'Optimisation :** `scipy.optimize` ou implémentation sur-mesure d'un algorithme des plus proches voisins (Nearest Neighbor) avec optimisation 2-opt pour une exécution ultra-rapide sans dépendances lourdes C++[cite: 2].
* **Services Géospatiaux :** API OpenStreetMap / Nominatim (Géocodage) et OSRM (Open Source Routing Machine) pour la matrice des distances[cite: 2].
* **Persistance des Données :** Base de données SQLite locale pour mémoriser les tournées, l'historique et le statut des colis (Livré, En cours, Absent)[cite: 2].

---
*Date de création : Juillet 2026*[cite: 2]