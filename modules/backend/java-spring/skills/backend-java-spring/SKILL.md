---
name: backend-java-spring
description: >-
  Enforces Java 21+ and Spring Boot 3 architecture, constructor injection,
  Jakarta Bean Validation, immutable DTO boundaries, transactional safety, and
  Maven/Gradle testing. Use whenever creating or modifying Spring controllers,
  services, repositories, security configs, or tests.
---

# Backend Java 21+ / Spring Boot 3 Playbook

## 1. Java 21+ & Spring Dependency Injection

- Prefer modern Java 21+ constructs: immutable `record` types for DTOs and value objects, `sealed` interfaces for bounded domain states, and unmodifiable collections (`List.copyOf`).
- **Constructor Injection Only:** Declare dependencies as `private final` fields injected via a single constructor; prohibit field `@Autowired` injection so classes remain immutable and testable without starting a Spring context.
- Bind environment configuration through `@ConfigurationProperties` records annotated with `@Validated` instead of scattering raw `@Value` placeholders.

## 2. DTO Boundaries & Bean Validation

- **Never Expose Entities:** Controllers must accept and return dedicated request/response DTOs (`record`s), never JPA `@Entity` instances—preventing mass-assignment vulnerabilities, `LazyInitializationException`, and accidental field exposure.
- Validate external payloads at controller boundaries using `@Valid` and Jakarta Bean Validation constraints (`@NotBlank`, `@NotNull`, `@Size`, `@Positive`), and map validation/domain errors consistently in a `@RestControllerAdvice` returning RFC 9457 `ProblemDetail` without internal stack traces.

## 3. Transactions, Persistence & Security

- Place `@Transactional` at application service method boundaries (never on controllers), and mark read-only queries with `@Transactional(readOnly = true)`.
- Never hold database transactions open across outbound HTTP/RPC calls; manage schema evolution deterministically with Flyway or Liquibase migrations (`spring.jpa.hibernate.ddl-auto=validate` in non-local environments).
- Enforce deny-by-default authorization in `SecurityFilterChain` (plus method security such as `@PreAuthorize` where needed) and never disable CSRF protections on browser/cookie-authenticated endpoints.

## 4. Testing & Verification Gate

- Isolate fast unit tests with JUnit 5 + Mockito (`@ExtendWith(MockitoExtension.class)`), verify HTTP serialization and validation via `@WebMvcTest`, and verify real queries/migrations via `@DataJpaTest` or `@SpringBootTest` with Testcontainers.
- Run the project build tool verification before opening a PR:

```sh
./mvnw test      # Maven
./gradlew test   # Gradle
```
