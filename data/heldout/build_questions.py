"""Source of truth for the Pagila held-out set; writes questions.jsonl.

Non-integer answers name their rounding so a correct prediction can match
exactly under BIRD-style set equality.
"""
import json
from pathlib import Path

S, M, C = "simple", "moderate", "challenging"

CUSTOMER_COUNTRY = (
    "FROM customer cu JOIN address a ON cu.address_id = a.address_id "
    "JOIN city ci ON a.city_id = ci.city_id "
    "JOIN country co ON ci.country_id = co.country_id"
)
REVENUE_BY_FILM = (
    "FROM payment p JOIN rental r ON p.rental_id = r.rental_id "
    "JOIN inventory i ON r.inventory_id = i.inventory_id"
)

QUESTIONS = [
    # --- simple (12) ---
    (S, "How many films are rated PG-13?", "",
     "SELECT COUNT(*) FROM film WHERE rating = 'PG-13'"),
    (S, "How many customers are inactive?",
     "inactive customers have active = 0",
     "SELECT COUNT(*) FROM customer WHERE active = 0"),
    (S, "What is the average film length in minutes, rounded to two decimal places?", "",
     "SELECT ROUND(AVG(length), 2) FROM film"),
    (S, "List the titles of films longer than 180 minutes.", "",
     "SELECT title FROM film WHERE length > 180"),
    (S, "How many actors have the last name Davis?", "",
     "SELECT COUNT(*) FROM actor WHERE last_name = 'DAVIS'"),
    (S, "What is the email address of the customer Mary Smith?", "",
     "SELECT email FROM customer WHERE first_name = 'MARY' AND last_name = 'SMITH'"),
    (S, "How many payments were greater than $10?", "",
     "SELECT COUNT(*) FROM payment WHERE amount > 10"),
    (S, "How many cities in Canada are in the database?", "",
     "SELECT COUNT(*) FROM city ci JOIN country co ON ci.country_id = co.country_id "
     "WHERE co.country = 'Canada'"),
    (S, "How many rentals have not been returned yet?",
     "a rental that has not been returned has no return_date",
     "SELECT COUNT(*) FROM rental WHERE return_date IS NULL"),
    (S, "What was the total amount of payments made in March 2022?", "",
     "SELECT SUM(amount) FROM payment "
     "WHERE payment_date >= '2022-03-01' AND payment_date < '2022-04-01'"),
    (S, "How many films include Deleted Scenes as a special feature?", "",
     "SELECT COUNT(*) FROM film WHERE 'Deleted Scenes' = ANY(special_features)"),
    (S, "List the names of all film categories.", "",
     "SELECT name FROM category"),

    # --- moderate (20) ---
    (M, "Which country has the most customers?", "",
     f"SELECT co.country {CUSTOMER_COUNTRY} "
     "GROUP BY co.country ORDER BY COUNT(*) DESC LIMIT 1"),
    (M, "How many films are in the Horror category?", "",
     "SELECT COUNT(*) FROM film_category fc JOIN category c ON fc.category_id = c.category_id "
     "WHERE c.name = 'Horror'"),
    (M, "List the titles of films that Penelope Guiness acted in.", "",
     "SELECT f.title FROM film f JOIN film_actor fa ON f.film_id = fa.film_id "
     "JOIN actor a ON fa.actor_id = a.actor_id "
     "WHERE a.first_name = 'PENELOPE' AND a.last_name = 'GUINESS'"),
    (M, "What is the total payment amount processed by each staff member? "
        "Give their first name, last name and the total.", "",
     "SELECT s.first_name, s.last_name, SUM(p.amount) FROM payment p "
     "JOIN staff s ON p.staff_id = s.staff_id "
     "GROUP BY s.staff_id, s.first_name, s.last_name"),
    (M, "Which customer has rented the most films? Give their first and last name.", "",
     "SELECT c.first_name, c.last_name FROM rental r "
     "JOIN customer c ON r.customer_id = c.customer_id "
     "GROUP BY c.customer_id, c.first_name, c.last_name ORDER BY COUNT(*) DESC LIMIT 1"),
    (M, "How many distinct films does store 2 have in its inventory?", "",
     "SELECT COUNT(DISTINCT film_id) FROM inventory WHERE store_id = 2"),
    (M, "What is the average rental rate for each film rating, rounded to two "
        "decimal places? Give the rating and the average.", "",
     "SELECT rating, ROUND(AVG(rental_rate), 2) FROM film GROUP BY rating"),
    (M, "Which film category has the longest average film length?", "",
     "SELECT c.name FROM film f JOIN film_category fc ON f.film_id = fc.film_id "
     "JOIN category c ON fc.category_id = c.category_id "
     "GROUP BY c.category_id, c.name ORDER BY AVG(f.length) DESC LIMIT 1"),
    (M, "List the titles of films that no store has a copy of.", "",
     "SELECT f.title FROM film f WHERE NOT EXISTS "
     "(SELECT 1 FROM inventory i WHERE i.film_id = f.film_id)"),
    (M, "How many customers live in London?", "",
     f"SELECT COUNT(*) {CUSTOMER_COUNTRY} WHERE ci.city = 'London'"),
    (M, "What is the total payment revenue from films in the Sports category?", "",
     f"SELECT SUM(p.amount) {REVENUE_BY_FILM} "
     "JOIN film_category fc ON i.film_id = fc.film_id "
     "JOIN category c ON fc.category_id = c.category_id WHERE c.name = 'Sports'"),
    (M, "Which actor has appeared in the most films? Give their first and last name.", "",
     "SELECT a.first_name, a.last_name FROM film_actor fa "
     "JOIN actor a ON fa.actor_id = a.actor_id "
     "GROUP BY a.actor_id, a.first_name, a.last_name ORDER BY COUNT(*) DESC LIMIT 1"),
    (M, "How many rentals of store 1's inventory were made in July 2022?",
     "a rental belongs to the store that holds the rented inventory item",
     "SELECT COUNT(*) FROM rental r JOIN inventory i ON r.inventory_id = i.inventory_id "
     "WHERE i.store_id = 1 AND r.rental_date >= '2022-07-01' AND r.rental_date < '2022-08-01'"),
    (M, "What is the average total amount paid per customer, rounded to two decimal places?",
     "first total each customer's payments, then average those totals",
     "SELECT ROUND(AVG(total), 2) FROM "
     "(SELECT customer_id, SUM(amount) AS total FROM payment GROUP BY customer_id) t"),
    (M, "How many films are rated R and are longer than two hours?",
     "two hours is 120 minutes",
     "SELECT COUNT(*) FROM film WHERE rating = 'R' AND length > 120"),
    (M, "How many Comedy films are longer than the average length of all films?", "",
     "SELECT COUNT(*) FROM film f JOIN film_category fc ON f.film_id = fc.film_id "
     "JOIN category c ON fc.category_id = c.category_id "
     "WHERE c.name = 'Comedy' AND f.length > (SELECT AVG(length) FROM film)"),
    (M, "Which customers have more than one rental that has not been returned? "
        "Give their first and last names.",
     "a rental that has not been returned has no return_date",
     "SELECT c.first_name, c.last_name FROM rental r "
     "JOIN customer c ON r.customer_id = c.customer_id WHERE r.return_date IS NULL "
     "GROUP BY c.customer_id, c.first_name, c.last_name HAVING COUNT(*) > 1"),
    (M, "How many active customers does each store have? Give the store id and the count.",
     "active customers have active = 1",
     "SELECT store_id, COUNT(*) FROM customer WHERE active = 1 GROUP BY store_id"),
    (M, "What percentage of films have a rental rate of $0.99, rounded to two decimal places?", "",
     "SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE rental_rate = 0.99) / COUNT(*), 2) FROM film"),
    (M, "How many distinct customers have rented an Animation film?", "",
     "SELECT COUNT(DISTINCT r.customer_id) FROM rental r "
     "JOIN inventory i ON r.inventory_id = i.inventory_id "
     "JOIN film_category fc ON i.film_id = fc.film_id "
     "JOIN category c ON fc.category_id = c.category_id WHERE c.name = 'Animation'"),

    # --- challenging (8) ---
    (C, "What percentage of total payment revenue does each film category account for? "
        "Give the category name and the percentage rounded to two decimal places.", "",
     f"SELECT c.name, ROUND(100 * SUM(p.amount) / (SELECT SUM(amount) FROM payment), 2) "
     f"{REVENUE_BY_FILM} JOIN film_category fc ON i.film_id = fc.film_id "
     "JOIN category c ON fc.category_id = c.category_id GROUP BY c.category_id, c.name"),
    (C, "How many customers have spent more in total than the average customer?",
     "a customer's spend is the sum of their payments",
     "WITH t AS (SELECT customer_id, SUM(amount) AS total FROM payment GROUP BY customer_id) "
     "SELECT COUNT(*) FROM t WHERE total > (SELECT AVG(total) FROM t)"),
    (C, "Who are the top three actors by total payment revenue from rentals of films "
        "they appear in? Give their first and last names.", "",
     f"SELECT a.first_name, a.last_name {REVENUE_BY_FILM} "
     "JOIN film_actor fa ON i.film_id = fa.film_id JOIN actor a ON fa.actor_id = a.actor_id "
     "GROUP BY a.actor_id, a.first_name, a.last_name ORDER BY SUM(p.amount) DESC LIMIT 3"),
    (C, "For each store, which film category has the most rentals? "
        "Give the store id and the category name.",
     "a rental belongs to the store that holds the rented inventory item",
     "SELECT store_id, name FROM (SELECT i.store_id, c.name, RANK() OVER "
     "(PARTITION BY i.store_id ORDER BY COUNT(*) DESC) AS rk FROM rental r "
     "JOIN inventory i ON r.inventory_id = i.inventory_id "
     "JOIN film_category fc ON i.film_id = fc.film_id "
     "JOIN category c ON fc.category_id = c.category_id "
     "GROUP BY i.store_id, c.category_id, c.name) t WHERE rk = 1"),
    (C, "For each month of 2022, what was the total payment revenue and its change from "
        "the previous month? Give the month as YYYY-MM, the revenue and the change.",
     "the first month has no previous month, so its change is null",
     "SELECT month, revenue, revenue - LAG(revenue) OVER (ORDER BY month) FROM "
     "(SELECT TO_CHAR(payment_date, 'YYYY-MM') AS month, SUM(amount) AS revenue "
     "FROM payment WHERE payment_date >= '2022-01-01' AND payment_date < '2023-01-01' "
     "GROUP BY 1) t"),
    (C, "How many rentals were returned late?",
     "a rental is late when it was kept longer than the film's rental_duration in days",
     "SELECT COUNT(*) FROM rental r JOIN inventory i ON r.inventory_id = i.inventory_id "
     "JOIN film f ON i.film_id = f.film_id WHERE r.return_date IS NOT NULL "
     "AND r.return_date - r.rental_date > f.rental_duration * INTERVAL '1 day'"),
    (C, "Among returned rentals, which film category has the longest average time a "
        "rental was kept?",
     "time kept is return_date minus rental_date",
     "SELECT c.name FROM rental r JOIN inventory i ON r.inventory_id = i.inventory_id "
     "JOIN film_category fc ON i.film_id = fc.film_id "
     "JOIN category c ON fc.category_id = c.category_id WHERE r.return_date IS NOT NULL "
     "GROUP BY c.category_id, c.name ORDER BY AVG(r.return_date - r.rental_date) DESC LIMIT 1"),
    (C, "How many actors have appeared in at least one film of every rating?",
     "the ratings are G, PG, PG-13, R and NC-17",
     "SELECT COUNT(*) FROM (SELECT fa.actor_id FROM film_actor fa "
     "JOIN film f ON fa.film_id = f.film_id GROUP BY fa.actor_id "
     "HAVING COUNT(DISTINCT f.rating) = (SELECT COUNT(DISTINCT rating) FROM film)) t"),
]


def main() -> None:
    out = Path(__file__).with_name("questions.jsonl")
    with open(out, "w") as fh:
        for n, (difficulty, question, evidence, sql) in enumerate(QUESTIONS, 1):
            fh.write(json.dumps({
                "question_id": f"H{n:02d}",
                "db_id": "pagila",
                "question": question,
                "evidence": evidence,
                "SQL": sql,
                "difficulty": difficulty,
            }) + "\n")
    print(f"{len(QUESTIONS)} questions -> {out}")


if __name__ == "__main__":
    main()
